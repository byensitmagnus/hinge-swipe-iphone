//! Worker-tråden: login, swipe-loop og første besked. Ejer HingeClient.
//! UI'et taler kun med den via `Cmd` (ind) og `Ev` (ud).

use crate::logic::{self, Chan, Settings, State};
use hinge_rs::client::RecsFetchConfig;
use hinge_rs::errors::HingeError;
use hinge_rs::models::{MessageData, RateInput, SendMessagePayload};
use hinge_rs::settings::Settings as HingeSettings;
use hinge_rs::storage::FsStorage;
use hinge_rs::Client;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{Receiver, Sender};
use std::sync::Arc;
use std::time::Duration;

#[derive(Debug)]
pub enum Cmd {
    SendSms(String),
    Otp(String),
    EmailCode(String),
    Logout,
    Start(Settings),
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Phase {
    LoggedOut,
    WaitOtp,
    WaitEmail,
    Ready,
    Running,
}

#[derive(Debug)]
pub enum Ev {
    Log(String),
    Phase(Phase),
    /// (likes i dag, første beskeder i denne kørsel)
    Counters(u32, u32),
}

struct Emitter {
    tx: Sender<Ev>,
    ctx: Option<eframe::egui::Context>,
}

impl Emitter {
    fn send(&self, ev: Ev) {
        let _ = self.tx.send(ev);
        if let Some(ctx) = &self.ctx {
            ctx.request_repaint();
        }
    }
    fn log(&self, msg: impl Into<String>) {
        self.send(Ev::Log(msg.into()));
    }
}

pub fn data_dir() -> PathBuf {
    if let Some(dir) = std::env::var_os("HINGE_DATA_DIR") {
        return PathBuf::from(dir);
    }
    let base = std::env::var_os("APPDATA").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("."));
    base.join("HingeAutoSwipe")
}

pub fn settings_path() -> PathBuf {
    data_dir().join("settings.json")
}
fn session_path() -> PathBuf {
    data_dir().join("session.json")
}
fn state_path() -> PathBuf {
    data_dir().join("state.json")
}

pub fn load_settings() -> Settings {
    std::fs::read_to_string(settings_path())
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

pub fn save_settings(s: &Settings) {
    let _ = std::fs::create_dir_all(data_dir());
    if let Ok(json) = serde_json::to_string_pretty(s) {
        let _ = std::fs::write(settings_path(), json);
    }
}

fn load_state() -> State {
    std::fs::read_to_string(state_path()).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default()
}

fn save_state(st: &State) {
    let _ = std::fs::create_dir_all(data_dir());
    if let Ok(json) = serde_json::to_string(st) {
        let _ = std::fs::write(state_path(), json);
    }
}

fn today() -> String {
    chrono::Local::now().format("%Y-%m-%d").to_string()
}

fn rnd() -> f64 {
    rand::random_range(0.0..1.0)
}

/// Sov i små skridt, så Stop virker med det samme. Returnerer true hvis stoppet.
async fn nap(secs: f64, stop: &AtomicBool) -> bool {
    let mut left = secs;
    while left > 0.0 {
        if stop.load(Ordering::Relaxed) {
            return true;
        }
        let step = left.min(0.25);
        tokio::time::sleep(Duration::from_secs_f64(step)).await;
        left -= step;
    }
    stop.load(Ordering::Relaxed)
}

fn build_client(phone: &str) -> Result<Client<FsStorage>, HingeError> {
    let _ = std::fs::create_dir_all(data_dir());
    let mut settings = HingeSettings { device_region: "DK".into(), accept_language: "da-DK".into(), ..HingeSettings::default() };
    // Kun til end-to-end-test mod en lokal falsk server
    if let Ok(mock) = std::env::var("HINGE_MOCK_URL") {
        settings.base_url = mock.clone();
        settings.sendbird_api_url = format!("{mock}/sb");
        settings.sendbird_ws_url = format!("{}/ws", mock.replacen("http", "ws", 1));
    }
    let mut client = Client::builder()
        .phone_number(phone)
        .settings(settings)
        // ét feed-kald ad gangen – roligere end standardens tre i træk
        .recs_fetch_config(RecsFetchConfig { multi_fetch_count: 1, ..RecsFetchConfig::default() })
        .build()?;
    client.persistence().configure(Some(session_path().to_string_lossy().into_owned()), None, true);
    Ok(client)
}

pub fn spawn(rx: Receiver<Cmd>, tx: Sender<Ev>, ctx: Option<eframe::egui::Context>, stop: Arc<AtomicBool>) {
    std::thread::spawn(move || {
        let rt = tokio::runtime::Builder::new_current_thread().enable_all().build().expect("tokio");
        rt.block_on(run(rx, Emitter { tx, ctx }, stop));
    });
}

async fn run(rx: Receiver<Cmd>, out: Emitter, stop: Arc<AtomicBool>) {
    let mut client: Option<Client<FsStorage>> = None;
    let mut email_case: Option<String> = None;

    // Genbrug gemt login
    let saved = load_settings();
    if !saved.phone.is_empty() && session_path().exists() {
        if let Ok(mut c) = build_client(&saved.phone) {
            match c.auth().is_session_valid().await {
                Ok(true) => {
                    out.log("Logget ind med gemt session.");
                    out.send(Ev::Phase(Phase::Ready));
                    client = Some(c);
                }
                _ => out.log("Gemt session er udløbet – log ind igen."),
            }
        }
    }

    while let Ok(cmd) = rx.recv() {
        match cmd {
            Cmd::SendSms(phone) => match build_client(phone.trim()) {
                Ok(mut c) => match c.auth().initiate_sms().await {
                    Ok(()) => {
                        out.log("SMS sendt – indtast koden.");
                        client = Some(c);
                        out.send(Ev::Phase(Phase::WaitOtp));
                    }
                    Err(e) => out.log(format!("Kunne ikke sende SMS: {e}")),
                },
                Err(e) => out.log(format!("Fejl: {e}")),
            },
            Cmd::Otp(code) => {
                let Some(c) = client.as_mut() else { continue };
                match c.auth().submit_otp(code.trim()).await {
                    Ok(_) => finish_login(c, &out),
                    Err(HingeError::Email2FA { case_id, email }) => {
                        out.log(format!("Hinge sendte en kode til {email} – indtast den."));
                        email_case = Some(case_id);
                        out.send(Ev::Phase(Phase::WaitEmail));
                    }
                    Err(e) => out.log(format!("Forkert kode eller fejl: {e}")),
                }
            }
            Cmd::EmailCode(code) => {
                let (Some(c), Some(case)) = (client.as_mut(), email_case.clone()) else { continue };
                match c.auth().submit_email_code(&case, code.trim()).await {
                    Ok(_) => finish_login(c, &out),
                    Err(e) => out.log(format!("Forkert email-kode eller fejl: {e}")),
                }
            }
            Cmd::Logout => {
                let _ = std::fs::remove_file(session_path());
                client = None;
                out.log("Logget ud.");
                out.send(Ev::Phase(Phase::LoggedOut));
            }
            Cmd::Start(settings) => {
                let Some(c) = client.as_mut() else { continue };
                stop.store(false, Ordering::Relaxed);
                out.send(Ev::Phase(Phase::Running));
                swipe(c, &settings.sanitized(), &out, &stop).await;
                out.send(Ev::Phase(Phase::Ready));
            }
        }
    }
}

fn finish_login(c: &mut Client<FsStorage>, out: &Emitter) {
    let _ = c.persistence().save_session(&session_path().to_string_lossy());
    out.log("Logget ind.");
    out.send(Ev::Phase(Phase::Ready));
}

async fn swipe(c: &mut Client<FsStorage>, s: &Settings, out: &Emitter, stop: &AtomicBool) {
    let mut st = load_state();
    st.roll_date(&today());
    let mut session_openers = 0u32;
    let mut errors_in_a_row = 0u32;
    let mut since_break = 0u32;
    let mut next_break = logic::swipes_until_break(rnd());
    let mut since_match_check = 0u32;

    let started = std::time::Instant::now();
    let hour = || chrono::Local::now().format("%H").to_string().parse::<u32>().unwrap_or(12);
    if !logic::in_active_hours(s, hour()) {
        out.log(format!("Uden for tidsrummet {}–{} – starter ikke (ret i indstillinger).", s.active_from, s.active_to));
        return;
    }
    out.log(if s.dry_run { "Prøvekørsel – der sendes ingenting." } else { "Starter – roligt tempo." });
    out.send(Ev::Counters(st.likes_today, session_openers));

    // Grundlinje FØR første like: matches der findes nu er "eksisterende", alt nyt bagefter får besked
    if s.send_openers && !st.baseline_done {
        session_openers += send_openers(c, s, &mut st, out, stop).await;
    }

    'run: loop {
        if st.cap_reached(s) {
            out.log(format!("Dagens grænse på {} er nået.", s.daily_cap));
            break;
        }
        if nap(2.0 + rnd() * 3.0, stop).await {
            break;
        }
        let recs = match c.recommendations().get().await {
            Ok(r) => r,
            Err(e) => {
                out.log(format!("Kunne ikke hente profiler: {e}"));
                break;
            }
        };
        let subjects: Vec<_> = recs
            .feeds
            .iter()
            .flat_map(|f| f.subjects.iter().map(move |sub| (sub.clone(), f.origin.clone())))
            .collect();
        if subjects.is_empty() {
            out.log("Ingen flere profiler lige nu.");
            break;
        }

        for (sub, feed_origin) in subjects {
            if stop.load(Ordering::Relaxed) || st.cap_reached(s) {
                break 'run;
            }
            if s.session_minutes > 0 && started.elapsed().as_secs() >= u64::from(s.session_minutes) * 60 {
                out.log(format!("Sessionen har kørt {} min – stopper (start igen senere).", s.session_minutes));
                break 'run;
            }
            if !logic::in_active_hours(s, hour()) {
                out.log("Tidsrummet er slut – stopper.");
                break 'run;
            }
            if s.dry_run {
                out.log("(prøve) ville like en profil");
            } else {
                let input = RateInput {
                    subject_id: sub.subject_id.clone(),
                    rating_token: sub.rating_token.clone(),
                    origin: sub.origin.clone().or(Some(feed_origin)),
                    use_superlike: None,
                    photo: None,
                    answer_text: None,
                    question_text: None,
                    content_id: None,
                    comment: None,
                };
                match c.ratings().rate_user(input).await {
                    Ok(resp) => {
                        errors_in_a_row = 0;
                        st.likes_today += 1;
                        out.log(format!("♥ Liket (likes tilbage ifølge Hinge: {})", resp.limit.likes));
                        out.send(Ev::Counters(st.likes_today, session_openers));
                        save_state(&st);
                    }
                    Err(e) => {
                        errors_in_a_row += 1;
                        out.log(format!("Like fejlede: {e}"));
                        if logic::is_fatal_error(&e.to_string()) {
                            out.log("Hinge afviser os (login/spærring/for mange kald) – stopper med det samme. Vent et par timer, og log ind igen.");
                            break 'run;
                        }
                        if errors_in_a_row >= 3 {
                            out.log("For mange fejl i træk – stopper. Hvis alle likes afvises, kræver Hinge muligvis et foto/prompt-match, som appen ikke kan se.");
                            break 'run;
                        }
                    }
                }
            }

            since_break += 1;
            since_match_check += 1;
            if s.send_openers && since_match_check >= 10 {
                since_match_check = 0;
                session_openers += send_openers(c, s, &mut st, out, stop).await;
                out.send(Ev::Counters(st.likes_today, session_openers));
            }

            if nap(logic::human_delay(s, rnd(), rnd()), stop).await {
                break 'run;
            }
            if since_break >= next_break {
                since_break = 0;
                next_break = logic::swipes_until_break(rnd());
                let pause = logic::long_pause(s, rnd());
                out.log(format!("Holder en pause på {pause:.0} s."));
                if nap(pause, stop).await {
                    break 'run;
                }
            }
        }
        if s.dry_run {
            break;
        }
    }

    if s.send_openers && !stop.load(Ordering::Relaxed) {
        session_openers += send_openers(c, s, &mut st, out, stop).await;
    }
    save_state(&st);
    out.send(Ev::Counters(st.likes_today, session_openers));
    out.log(if stop.load(Ordering::Relaxed) { "Stoppet." } else { "Færdig." });
}

/// Find nye matches uden beskeder og send første besked. Returnerer antal sendt.
async fn send_openers(c: &mut Client<FsStorage>, s: &Settings, st: &mut State, out: &Emitter, stop: &AtomicBool) -> u32 {
    let me = c.session().hinge_identity_id.unwrap_or_default();
    let channels = match c.chat().channels(100).await {
        Ok(r) => r.channels,
        Err(e) => {
            out.log(format!("Kunne ikke hente matches: {e}"));
            return 0;
        }
    };
    let list: Vec<Chan> = channels
        .iter()
        .map(|ch| {
            let peer = ch.members.iter().find(|m| m.user_id != me);
            Chan {
                url: ch.channel_url.clone(),
                peer_id: peer.map(|m| m.user_id.clone()).unwrap_or_default(),
                peer_name: peer.map(|m| m.nickname.clone()).unwrap_or_default(),
                // kun rigtige beskeder (MESG) tæller – systembeskeder om matchet gør ikke
                has_messages: ch.last_message.as_ref().is_some_and(|m| m.msg_type == "MESG"),
            }
        })
        .collect();

    let fresh: Vec<Chan> = logic::fresh_channels(&list, &st.seen).into_iter().cloned().collect();

    if !st.baseline_done && !s.message_existing {
        for ch in &fresh {
            st.seen.insert(ch.url.clone());
        }
        st.baseline_done = true;
        save_state(st);
        if !fresh.is_empty() {
            out.log(format!("{} eksisterende match(es) uden beskeder springes over (kun nye får første besked).", fresh.len()));
        }
        return 0;
    }
    st.baseline_done = true;

    let mut sent = 0;
    for (i, ch) in fresh.iter().enumerate() {
        if stop.load(Ordering::Relaxed) {
            break;
        }
        let Some(text) = logic::pick_opener(&s.openers, &ch.peer_name, st.seen.len() + i) else {
            out.log("Ingen første besked indtastet – springer over.");
            break;
        };
        out.log(format!("Nyt match: {} 🎉", logic::first_name(&ch.peer_name)));
        if s.dry_run {
            out.log(format!("(prøve) ville skrive: {text}"));
            continue;
        }
        // lidt ventetid, som om man lige skal nå at se matchet
        if nap(logic::opener_wait(s, rnd()), stop).await {
            break;
        }
        let payload = SendMessagePayload {
            dedup_id: None,
            ays: false,
            match_message: false,
            message_type: "message".into(),
            message_data: MessageData { message: text.clone() },
            subject_id: ch.peer_id.clone(),
            origin: "chat".into(),
        };
        // Højst én gang: en timeout fra Sendbird er tvetydig (beskeden kan være landet), så
        // kanalen markeres som håndteret før afsendelse og gensendes aldrig automatisk.
        st.seen.insert(ch.url.clone());
        save_state(st);
        match c.chat().send_message(payload).await {
            Ok(_) => {
                sent += 1;
                out.log(format!("✉ Skrev til {}: {text}", logic::first_name(&ch.peer_name)));
            }
            Err(e) => out.log(format!(
                "Kunne ikke bekræfte besked til {} (sendes ikke igen automatisk – tjek i Hinge): {e}",
                logic::first_name(&ch.peer_name)
            )),
        }
    }
    sent
}

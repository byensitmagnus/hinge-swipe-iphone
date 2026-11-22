#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod engine;
mod logic;

use eframe::egui;
use engine::{Cmd, Ev, Phase};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::Arc;

struct App {
    settings: logic::Settings,
    phase: Phase,
    code: String,
    log: Vec<String>,
    likes_today: u32,
    openers_sent: u32,
    cmd: Sender<Cmd>,
    events: Receiver<Ev>,
    stop: Arc<AtomicBool>,
}

impl App {
    fn new(cc: &eframe::CreationContext<'_>) -> Self {
        let (cmd_tx, cmd_rx) = channel();
        let (ev_tx, ev_rx) = channel();
        let stop = Arc::new(AtomicBool::new(false));
        engine::spawn(cmd_rx, ev_tx, Some(cc.egui_ctx.clone()), stop.clone());
        Self {
            settings: engine::load_settings(),
            phase: Phase::LoggedOut,
            code: String::new(),
            log: vec!["Klar.".into()],
            likes_today: 0,
            openers_sent: 0,
            cmd: cmd_tx,
            events: ev_rx,
            stop,
        }
    }

    fn drain(&mut self) {
        while let Ok(ev) = self.events.try_recv() {
            match ev {
                Ev::Log(m) => {
                    let t = chrono::Local::now().format("%H:%M:%S");
                    self.log.push(format!("{t}  {m}"));
                    if self.log.len() > 300 {
                        self.log.remove(0);
                    }
                }
                Ev::Phase(p) => {
                    self.phase = p;
                    self.code.clear();
                }
                Ev::Counters(l, o) => {
                    self.likes_today = l;
                    self.openers_sent = o;
                }
            }
        }
    }

    fn login_ui(&mut self, ui: &mut egui::Ui) {
        match self.phase {
            Phase::LoggedOut => {
                ui.label("Telefonnummer (med landekode)");
                ui.text_edit_singleline(&mut self.settings.phone);
                if ui.button("Send SMS-kode").clicked() && !self.settings.phone.trim().is_empty() {
                    engine::save_settings(&self.settings);
                    let _ = self.cmd.send(Cmd::SendSms(self.settings.phone.clone()));
                }
            }
            Phase::WaitOtp | Phase::WaitEmail => {
                let what = if self.phase == Phase::WaitOtp { "SMS-kode" } else { "Email-kode fra Hinge" };
                ui.label(what);
                let resp = ui.text_edit_singleline(&mut self.code);
                let go = ui.button("Log ind").clicked()
                    || (resp.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter)));
                if go && !self.code.trim().is_empty() {
                    let c = self.code.clone();
                    let _ = self.cmd.send(if self.phase == Phase::WaitOtp { Cmd::Otp(c) } else { Cmd::EmailCode(c) });
                }
            }
            _ => {}
        }
    }

    fn main_ui(&mut self, ui: &mut egui::Ui) {
        let running = self.phase == Phase::Running;
        ui.horizontal(|ui| {
            if running {
                if ui.add(egui::Button::new("■ Stop").min_size(egui::vec2(120.0, 36.0))).clicked() {
                    self.stop.store(true, Ordering::Relaxed);
                }
            } else if ui.add(egui::Button::new("▶ Start swipe").min_size(egui::vec2(120.0, 36.0))).clicked() {
                engine::save_settings(&self.settings);
                let _ = self.cmd.send(Cmd::Start(self.settings.clone()));
            }
            ui.label(format!("Likes i dag: {}   Første beskeder: {}", self.likes_today, self.openers_sent));
        });

        ui.add_enabled_ui(!running, |ui| {
            ui.separator();
            ui.label("Første besked til nye matches (én pr. linje – {navn} bliver til matchets fornavn)");
            ui.add(egui::TextEdit::multiline(&mut self.settings.openers).desired_rows(3).desired_width(f32::INFINITY));
            ui.checkbox(&mut self.settings.send_openers, "Send første besked automatisk ved nyt match");
            ui.checkbox(&mut self.settings.message_existing, "Skriv også til eksisterende matches uden beskeder");

            ui.add_space(4.0);
            ui.label("Tempo");
            ui.horizontal(|ui| {
                ui.label("Pause mellem swipes");
                ui.add(egui::DragValue::new(&mut self.settings.min_delay).range(2.0..=120.0).suffix(" s"));
                ui.label("til");
                ui.add(egui::DragValue::new(&mut self.settings.max_delay).range(2.0..=300.0).suffix(" s"));
            });
            ui.horizontal(|ui| {
                ui.label("Lang pause hver 12–25. swipe");
                ui.add(egui::DragValue::new(&mut self.settings.long_pause_min).range(0.0..=600.0).suffix(" s"));
                ui.label("til");
                ui.add(egui::DragValue::new(&mut self.settings.long_pause_max).range(0.0..=900.0).suffix(" s"));
            });
            ui.horizontal(|ui| {
                ui.label("Max swipes pr. dag (0 = ingen grænse)");
                ui.add(egui::DragValue::new(&mut self.settings.daily_cap).range(0..=2000));
            });
            ui.horizontal(|ui| {
                ui.label("Stop efter (min, 0 = aldrig)");
                ui.add(egui::DragValue::new(&mut self.settings.session_minutes).range(0..=600));
                ui.label("   Kun mellem kl.");
                ui.add(egui::DragValue::new(&mut self.settings.active_from).range(0..=24));
                ui.label("og");
                ui.add(egui::DragValue::new(&mut self.settings.active_to).range(0..=24));
            });
            ui.checkbox(&mut self.settings.dry_run, "Prøvekørsel (sender ingenting)");
            if ui.small_button("Log ud").clicked() {
                let _ = self.cmd.send(Cmd::Logout);
            }
        });
    }
}

impl eframe::App for App {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        self.drain();
        egui::Frame::central_panel(ui.style()).show(ui, |ui| {
            ui.heading("Hinge Auto Swipe");
            ui.add_space(6.0);
            if matches!(self.phase, Phase::Ready | Phase::Running) {
                self.main_ui(ui);
            } else {
                self.login_ui(ui);
            }
            ui.separator();
            egui::ScrollArea::vertical().stick_to_bottom(true).auto_shrink([false, false]).show(ui, |ui| {
                for line in &self.log {
                    ui.label(egui::RichText::new(line).monospace().size(12.0));
                }
            });
        });
        // lille puls, så loggen opdateres selv uden mus
        ui.ctx().request_repaint_after(std::time::Duration::from_millis(500));
    }

    fn on_exit(&mut self, _gl: Option<&eframe::glow::Context>) {
        self.stop.store(true, Ordering::Relaxed);
        engine::save_settings(&self.settings);
    }
}

/// Uden vindue: logger ind med kode 000000 og kører én swipe-session. Bruges til end-to-end-test.
fn headless() {
    let (cmd_tx, cmd_rx) = channel();
    let (ev_tx, ev_rx) = channel();
    engine::spawn(cmd_rx, ev_tx, None, Arc::new(AtomicBool::new(false)));
    let settings = engine::load_settings();
    // Release-build har ingen konsol, så log til fil
    let log_path = engine::data_dir().join("e2e.log");
    let say = |line: String| {
        use std::io::Write;
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(&log_path) {
            let _ = writeln!(f, "{line}");
        }
    };
    let _ = cmd_tx.send(Cmd::SendSms(settings.phone.clone()));
    let mut started = false;
    while let Ok(ev) = ev_rx.recv_timeout(std::time::Duration::from_secs(180)) {
        match ev {
            Ev::Log(m) => say(m),
            Ev::Counters(l, o) => say(format!("COUNTERS likes={l} openers={o}")),
            Ev::Phase(Phase::WaitOtp) => {
                let _ = cmd_tx.send(Cmd::Otp("000000".into()));
            }
            Ev::Phase(Phase::Ready) if !started => {
                started = true;
                let _ = cmd_tx.send(Cmd::Start(settings.clone()));
            }
            Ev::Phase(Phase::Ready) => break,
            Ev::Phase(_) => {}
        }
    }
}

fn main() -> eframe::Result {
    if std::env::args().any(|a| a == "--headless") {
        headless();
        return Ok(());
    }
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default().with_inner_size([560.0, 700.0]).with_min_inner_size([480.0, 520.0]),
        ..Default::default()
    };
    eframe::run_native("Hinge Auto Swipe", options, Box::new(|cc| Ok(Box::new(App::new(cc)))))
}

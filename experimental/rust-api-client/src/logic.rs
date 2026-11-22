//! Ren logik uden netværk og UI – tempo, første besked, nye matches, daglig tæller.
//! Alt tilfældigt kommer ind som parameter (`r` i 0..1), så det kan testes.

use serde::{Deserialize, Serialize};
use std::collections::HashSet;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    pub phone: String,
    /// Første besked(er) til nye matches. Én pr. linje; {navn} bliver til matchets fornavn.
    pub openers: String,
    /// Pause mellem swipes i sekunder (tilfældig mellem min og max).
    pub min_delay: f64,
    pub max_delay: f64,
    /// Længere pause efter hver 12–25 swipes, i sekunder.
    pub long_pause_min: f64,
    pub long_pause_max: f64,
    /// Maks swipes pr. dag (0 = ingen grænse).
    pub daily_cap: u32,
    /// Ventetid før første besked sendes (sekunder) – ligner et menneske.
    pub opener_wait_min: f64,
    pub opener_wait_max: f64,
    pub send_openers: bool,
    /// Stop automatisk efter så mange minutter (0 = ingen grænse). Korte sessioner ligner et menneske.
    pub session_minutes: u32,
    /// Kun swipe mellem disse klokkeslæt (lokal tid, hele timer). 0 og 24 = hele døgnet.
    pub active_from: u32,
    pub active_to: u32,
    /// Skriv også til matches, der allerede fandtes før første kørsel.
    pub message_existing: bool,
    pub dry_run: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            phone: String::new(),
            openers: "Hej {navn}! Jeg går direkte til sagen: skal vi tage en kaffe eller en drink i den her uge? ☕"
                .into(),
            min_delay: 5.0,
            max_delay: 12.0,
            long_pause_min: 45.0,
            long_pause_max: 120.0,
            daily_cap: 80,
            opener_wait_min: 45.0,
            opener_wait_max: 180.0,
            send_openers: true,
            session_minutes: 30,
            active_from: 8,
            active_to: 23,
            message_existing: false,
            dry_run: false,
        }
    }
}

impl Settings {
    /// Ret urimelige værdier, så en tastefejl ikke giver 0-sekunders-spam.
    pub fn sanitized(mut self) -> Self {
        self.min_delay = self.min_delay.max(2.0);
        self.max_delay = self.max_delay.max(self.min_delay);
        self.long_pause_min = self.long_pause_min.max(0.0);
        self.long_pause_max = self.long_pause_max.max(self.long_pause_min);
        self.opener_wait_min = self.opener_wait_min.max(0.0);
        self.opener_wait_max = self.opener_wait_max.max(self.opener_wait_min);
        self.active_from = self.active_from.min(24);
        self.active_to = self.active_to.min(24);
        self
    }
}

fn lerp(lo: f64, hi: f64, r: f64) -> f64 {
    lo + (hi - lo) * r.clamp(0.0, 1.0)
}

/// Pause før næste swipe.
pub fn swipe_delay(s: &Settings, r: f64) -> f64 {
    lerp(s.min_delay, s.max_delay, r)
}

/// Som `swipe_delay`, men ca. hver 10. gang en ekstra "kiggede lidt længere"-pause (op til 3× max).
/// `r1` vælger basis-pausen, `r2` afgør om og hvor meget der lægges oveni.
pub fn human_delay(s: &Settings, r1: f64, r2: f64) -> f64 {
    let extra = if r2 > 0.9 { (r2 - 0.9) * 10.0 * 3.0 * s.max_delay } else { 0.0 };
    swipe_delay(s, r1) + extra
}

/// Er klokkeslættet (0..24) inden for det tilladte tidsrum?
pub fn in_active_hours(s: &Settings, hour: u32) -> bool {
    if s.active_from == s.active_to || (s.active_from == 0 && s.active_to == 24) {
        return true;
    }
    if s.active_from < s.active_to {
        hour >= s.active_from && hour < s.active_to
    } else {
        hour >= s.active_from || hour < s.active_to // over midnat
    }
}

/// Fejl der betyder "Hinge har set os" (login udløbet, spærret, for mange kald) – stop med det samme.
pub fn is_fatal_error(msg: &str) -> bool {
    let m = msg.to_lowercase();
    ["401", "403", "429", "unauthorized", "forbidden", "too many", "rate limit", "banned", "suspended"]
        .iter()
        .any(|k| m.contains(k))
}

/// Ventetid før første besked.
pub fn opener_wait(s: &Settings, r: f64) -> f64 {
    lerp(s.opener_wait_min, s.opener_wait_max, r)
}

/// Længere pause efter et antal swipes.
pub fn long_pause(s: &Settings, r: f64) -> f64 {
    lerp(s.long_pause_min, s.long_pause_max, r)
}

/// Antal swipes til næste lange pause (12..=25).
pub fn swipes_until_break(r: f64) -> u32 {
    12 + (r.clamp(0.0, 0.999_999) * 14.0) as u32
}

pub fn first_name(nickname: &str) -> String {
    nickname.split_whitespace().next().unwrap_or("").to_string()
}

/// Vælg en opener og indsæt navn. `pick` vælger blandt linjerne (modulo).
pub fn pick_opener(openers: &str, nickname: &str, pick: usize) -> Option<String> {
    let lines: Vec<&str> = openers.lines().map(str::trim).filter(|l| !l.is_empty()).collect();
    if lines.is_empty() {
        return None;
    }
    let name = first_name(nickname);
    let text = lines[pick % lines.len()].replace("{navn}", &name);
    // "Hej !" er værre end "Hej" – ryd op hvis navnet mangler
    Some(text.replace(" !", "!").replace("  ", " ").trim().to_string())
}

#[derive(Clone, Debug, PartialEq)]
pub struct Chan {
    pub url: String,
    pub peer_id: String,
    pub peer_name: String,
    /// Findes der mindst én rigtig besked (ikke systembesked)?
    pub has_messages: bool,
}

/// Kanaler uden beskeder, vi ikke har set før.
pub fn fresh_channels<'a>(chans: &'a [Chan], seen: &HashSet<String>) -> Vec<&'a Chan> {
    chans
        .iter()
        .filter(|c| !c.has_messages && !c.peer_id.is_empty() && !seen.contains(&c.url))
        .collect()
}

/// Daglig tæller + husk hvilke kanaler vi allerede har håndteret.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct State {
    pub date: String,
    pub likes_today: u32,
    pub seen: HashSet<String>,
    pub baseline_done: bool,
}

impl State {
    pub fn roll_date(&mut self, today: &str) {
        if self.date != today {
            self.date = today.to_string();
            self.likes_today = 0;
        }
    }

    pub fn cap_reached(&self, s: &Settings) -> bool {
        s.daily_cap > 0 && self.likes_today >= s.daily_cap
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn chan(url: &str, has: bool) -> Chan {
        Chan { url: url.into(), peer_id: format!("p-{url}"), peer_name: "Sofie K".into(), has_messages: has }
    }

    #[test]
    fn delay_stays_within_bounds_and_is_never_instant() {
        let s = Settings { min_delay: 0.0, max_delay: 0.0, ..Settings::default() }.sanitized();
        assert!(s.min_delay >= 2.0);
        let s = Settings::default();
        assert_eq!(swipe_delay(&s, 0.0), 5.0);
        assert_eq!(swipe_delay(&s, 1.0), 12.0);
        assert!((swipe_delay(&s, 0.5) - 8.5).abs() < 1e-9);
        assert_eq!(long_pause(&s, 0.0), 45.0);
    }

    #[test]
    fn sanitize_fixes_inverted_ranges() {
        let s = Settings { min_delay: 10.0, max_delay: 3.0, long_pause_min: 90.0, long_pause_max: 10.0, ..Settings::default() }
            .sanitized();
        assert!(s.max_delay >= s.min_delay && s.long_pause_max >= s.long_pause_min);
    }

    #[test]
    fn break_interval_is_12_to_25() {
        assert_eq!(swipes_until_break(0.0), 12);
        assert_eq!(swipes_until_break(1.0), 25);
        assert!((12..=25).contains(&swipes_until_break(0.5)));
    }

    #[test]
    fn opener_uses_first_name_and_rotates() {
        let o = "Hej {navn}! Kaffe?\nHey {navn}, drink?";
        assert_eq!(pick_opener(o, "Sofie Krogh", 0).unwrap(), "Hej Sofie! Kaffe?");
        assert_eq!(pick_opener(o, "Sofie Krogh", 1).unwrap(), "Hey Sofie, drink?");
        assert_eq!(pick_opener(o, "Sofie", 2).unwrap(), "Hej Sofie! Kaffe?");
    }

    #[test]
    fn opener_without_name_or_text() {
        assert_eq!(pick_opener("Hej {navn}! Kaffe?", "", 0).unwrap(), "Hej! Kaffe?");
        assert!(pick_opener("  \n ", "Sofie", 0).is_none());
    }

    #[test]
    fn only_new_empty_channels_are_fresh() {
        let chans = vec![chan("a", false), chan("b", true), chan("c", false)];
        let mut seen = HashSet::new();
        seen.insert("c".to_string());
        let fresh = fresh_channels(&chans, &seen);
        assert_eq!(fresh.len(), 1);
        assert_eq!(fresh[0].url, "a");
    }

    #[test]
    fn channel_without_peer_is_skipped() {
        let mut c = chan("a", false);
        c.peer_id.clear();
        assert!(fresh_channels(&[c], &HashSet::new()).is_empty());
    }

    #[test]
    fn daily_counter_resets_and_caps() {
        let mut st = State { date: "2026-11-20".into(), likes_today: 50, ..State::default() };
        let s = Settings { daily_cap: 60, ..Settings::default() };
        assert!(!st.cap_reached(&s));
        st.likes_today = 60;
        assert!(st.cap_reached(&s));
        st.roll_date("2026-11-21");
        assert_eq!(st.likes_today, 0);
        assert!(!st.cap_reached(&Settings { daily_cap: 0, ..Settings::default() }));
    }

    #[test]
    fn human_delay_adds_rare_long_pauses() {
        let s = Settings::default();
        assert_eq!(human_delay(&s, 0.0, 0.5), 5.0);
        assert!(human_delay(&s, 0.0, 1.0) > 12.0 && human_delay(&s, 0.0, 1.0) <= 5.0 + 36.0);
    }

    #[test]
    fn active_hours_window() {
        let s = Settings { active_from: 8, active_to: 23, ..Settings::default() };
        assert!(in_active_hours(&s, 8) && in_active_hours(&s, 22));
        assert!(!in_active_hours(&s, 23) && !in_active_hours(&s, 3));
        let night = Settings { active_from: 20, active_to: 4, ..Settings::default() };
        assert!(in_active_hours(&night, 23) && in_active_hours(&night, 2) && !in_active_hours(&night, 12));
        assert!(in_active_hours(&Settings { active_from: 0, active_to: 24, ..Settings::default() }, 3));
    }

    #[test]
    fn fatal_errors_detected() {
        assert!(is_fatal_error("http: status 429 Too Many Requests"));
        assert!(is_fatal_error("auth: 401"));
        assert!(!is_fatal_error("connection reset"));
    }

    #[test]
    fn settings_roundtrip_and_tolerate_missing_fields() {
        let s: Settings = serde_json::from_str(r#"{"phone":"+45123"}"#).unwrap();
        assert_eq!(s.phone, "+45123");
        assert_eq!(s.min_delay, 5.0);
    }
}

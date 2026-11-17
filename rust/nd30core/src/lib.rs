//! Native core of nd30fmt: Vietnamese spell checking (vspell.py), syllable rules (vphon.py) and
//! OCR diacritic restoration (mdlib/vnfix.py). Results must stay identical to the Python reference
//! (tests/common/test_core_parity.py); all positions are code-point offsets, as in Python.
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::cell::OnceCell;
use std::collections::{HashMap, HashSet};
use std::rc::Rc;
use std::sync::OnceLock;
use unicode_general_category::{get_general_category as gc, GeneralCategory as G};
use unicode_normalization::{char::canonical_combining_class as ccc, UnicodeNormalization};

// ------------------------------------------------------------------ character classes as Python sees them
fn is_alpha(c: char) -> bool {
    if c.is_ascii() {
        return c.is_ascii_alphabetic();
    }
    if matches!(c, '\u{c0}'..='\u{24f}' | '\u{1ea0}'..='\u{1ef9}') {
        return c != '×' && c != '÷'; // Latin letters with Vietnamese marks: skip the table lookup
    }
    matches!(gc(c), G::UppercaseLetter | G::LowercaseLetter | G::TitlecaseLetter | G::ModifierLetter | G::OtherLetter)
}
/// regex `[^\W\d_]`
fn is_tok(c: char) -> bool {
    if c.is_ascii() {
        return c.is_ascii_alphabetic();
    }
    is_alpha(c) || matches!(gc(c), G::LetterNumber | G::OtherNumber)
}
fn is_dec(c: char) -> bool {
    c.is_ascii_digit() || (!c.is_ascii() && gc(c) == G::DecimalNumber)
}
/// str.isalnum() and regex `[^\W_]`
fn is_alnum(c: char) -> bool {
    is_tok(c) || is_dec(c)
}
/// regex `\w`
fn is_w(c: char) -> bool {
    is_alnum(c) || c == '_'
}
/// str.isdigit()
fn is_digit(c: char) -> bool {
    is_dec(c)
        || matches!(c as u32, 0xB2 | 0xB3 | 0xB9 | 0x2070 | 0x2074..=0x2079 | 0x2080..=0x2089 | 0x2460..=0x2468
            | 0x2474..=0x247C | 0x2488..=0x2490 | 0x24EA | 0x24F5..=0x24FD | 0x24FF | 0x2776..=0x277E
            | 0x2780..=0x2788 | 0x278A..=0x2792)
}
/// str.isspace() and regex `\s`
fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\x1c'..='\x1f').contains(&c)
}
/// str.isupper()
fn is_upper_str(s: &str) -> bool {
    let mut cased = false;
    for c in s.chars() {
        if c.is_lowercase() || (!c.is_ascii() && gc(c) == G::TitlecaseLetter) {
            return false;
        }
        cased |= c.is_uppercase();
    }
    cased
}
fn first_upper(s: &str) -> bool {
    s.chars().next().is_some_and(|c| c.is_uppercase())
}
fn low1(c: char) -> char {
    let mut it = c.to_lowercase();
    match (it.next(), it.next()) {
        (Some(l), None) => l,
        _ => c,
    }
}
fn eq_ci(a: char, b: char) -> bool {
    a == b || (!(a.is_ascii() && b.is_ascii()) || a.is_ascii_alphabetic() && b.is_ascii_alphabetic()) && low1(a) == low1(b)
}
fn s_of(cs: &[char]) -> String {
    cs.iter().collect()
}
fn apply_case(src: &str, dst: &str) -> String {
    if src.chars().nth(1).is_some() && is_upper_str(src) {
        return dst.to_uppercase();
    }
    if first_upper(src) {
        let mut it = dst.chars();
        return match it.next() {
            Some(f) => f.to_uppercase().chain(it).collect(),
            None => String::new(),
        };
    }
    dst.to_string()
}
/// vspell._is_cap: "Abc" (first letter upper, the rest lower)
fn is_cap(tok: &str) -> bool {
    let mut it = tok.chars();
    it.next();
    let rest = it.as_str();
    first_upper(tok) && !is_upper_str(tok) && rest == rest.to_lowercase()
}

// ------------------------------------------------------------------ vphon: syllable rules, tone placement
const MARKS: [char; 6] = ['\0', '\u{301}', '\u{300}', '\u{309}', '\u{303}', '\u{323}'];
fn tone_of(c: char) -> u8 {
    MARKS.iter().position(|&m| m == c).filter(|&p| p > 0).unwrap_or(0) as u8
}
fn has_tone(c: char) -> bool {
    !c.is_ascii() && std::iter::once(c).nfd().any(|d| tone_of(d) > 0)
}
fn is_vowel(c: char) -> bool {
    "aăâeêioôơuưy".contains(c)
}
const ONSETS: [&str; 25] = ["ngh", "ng", "nh", "ph", "th", "tr", "ch", "gh", "kh", "b", "c", "d", "đ", "g", "h", "k",
    "l", "m", "n", "p", "r", "s", "t", "v", "x"];
const RIMES_TXT: &str = "a ac ach ai am an ang anh ao ap at au ay ăc ăm ăn ăng ăp ăt âc âm ân âng âp ât âu ây \
e ec em en eng eo ep et ê êch êm ên ênh êp êt êu i ia ich im in inh ip it iu iêc iêm iên iêng iêp iêt iêu \
yêm yên yêng yêt yêu o oc oi om on ong op ot oa oac oach oai oam oan oang oanh oao oap oat oay \
oăc oăm oăn oăng oăt oe oen oeo oet ô ôc ôi ôm ôn ông ôp ôt ơ ơi ơm ơn ơp ơt u uc ui um un ung up ut \
ua uôc uôi uôm uôn uông uôt uâ uân uât uâng uây uê uêch uênh uêu uy uya uych uyn uynh uyp uyt uyu uyên uyêt uyêu \
uơ ư ưa ưc ưi ưm ưng ưt ưu ươc ươi ươm ươn ương ươp ươt ươu y";
fn rimes() -> &'static HashSet<&'static str> {
    static R: OnceLock<HashSet<&'static str>> = OnceLock::new();
    R.get_or_init(|| RIMES_TXT.split_whitespace().collect())
}

/// 'hoà' -> ("hoa", 2): letters (keeping circumflex/horn/breve) and the tone (0 = none)
fn split_tone(s: &str) -> (String, u8) {
    if s.is_ascii() {
        return (s.to_string(), 0);
    }
    let mut tone = 0;
    let mut out = String::new();
    for c in s.nfd() {
        match tone_of(c) {
            0 => out.push(c),
            t => tone = t,
        }
    }
    (out.nfc().collect(), tone)
}
fn starts(b: &[char], p: &str) -> bool {
    p.chars().enumerate().all(|(i, c)| b.get(i) == Some(&c))
}
fn parse(b: &[char]) -> Option<(&'static str, &[char])> {
    if b.is_empty() {
        return None;
    }
    for q in ["qu", "gi"] {
        if starts(b, q) && b.len() > 2 && is_vowel(b[2]) {
            return Some((q, &b[2..]));
        }
    }
    for o in ONSETS {
        let n = o.chars().count();
        if starts(b, o) && b.len() > n && is_vowel(b[n]) {
            return Some((o, &b[n..]));
        }
    }
    is_vowel(b[0]).then_some(("", b))
}
fn valid_syllable(word: &str) -> bool {
    let (base, tone) = split_tone(&word.to_lowercase());
    let b: Vec<char> = base.chars().collect();
    let Some((onset, rime)) = parse(&b) else { return false };
    let r = s_of(rime);
    if !rimes().contains(r.as_str()) {
        return false;
    }
    let front = "ieêy".contains(rime[0]);
    let ok = match onset {
        "k" | "gh" | "ngh" => front,
        "g" => !"eêy".contains(rime[0]),
        "c" | "ng" => !front,
        _ => true,
    };
    let stop = matches!(rime[rime.len() - 1], 'c' | 'p' | 't') || r.ends_with("ch");
    ok && (!stop || matches!(tone, 1 | 5)) // p t c ch only carry sắc / nặng
}
fn looks_vietnamese(word: &str) -> bool {
    let (base, _) = split_tone(&word.to_lowercase());
    !base.is_empty() && base.chars().all(|c| "abcdđeghiklmnopqrstuvxyăâêôơư".contains(c))
}
/// vphon.correct_tone_index (new_style=false is also vnfix._tone_index without a reference word)
fn tone_index(b: &[char], new_style: bool) -> i32 {
    let mut idx: Vec<usize> = (0..b.len()).filter(|&i| is_vowel(b[i])).collect();
    if (starts(b, "qu") || starts(b, "gi")) && idx.len() > 1 && idx[0] == 1 {
        idx.remove(0);
    }
    let Some(&last) = idx.last() else { return -1 };
    if let Some(&i) = idx.iter().rev().find(|&&i| "êơâăô".contains(b[i])) {
        return i as i32;
    }
    if let Some(&i) = idx.iter().find(|&&i| b[i] == 'ư') {
        return i as i32;
    }
    if last < b.len() - 1 || idx.len() == 1 {
        return last as i32;
    }
    if new_style && idx.len() == 2 && matches!((b[idx[0]], b[idx[1]]), ('o', 'a') | ('o', 'e') | ('u', 'y')) {
        return idx[1] as i32;
    }
    (if idx.len() >= 3 { idx[1] } else { idx[0] }) as i32
}
fn put_mark(base: &str, i: i32, tone: u8) -> String {
    if i < 0 || !(1..=5).contains(&tone) {
        return base.to_string();
    }
    let mut out = String::new();
    for (k, c) in base.chars().enumerate() {
        out.push(c);
        if k == i as usize {
            out.push(MARKS[tone as usize]);
        }
    }
    out.nfc().collect()
}
fn place_tone(base: &str, tone: u8, new_style: bool) -> String {
    if tone == 0 {
        return base.to_string();
    }
    let b: Vec<char> = base.chars().collect();
    put_mark(base, tone_index(&b, new_style), tone)
}
#[derive(PartialEq, Clone, Copy)]
enum Style {
    NoTone,
    Old,
    New,
    Both,
    Bad,
}
fn tone_style(word: &str) -> Style {
    let (base, tone) = split_tone(&word.to_lowercase());
    if tone == 0 {
        return Style::NoTone;
    }
    let pos: Vec<usize> = word.nfc().enumerate().filter(|&(_, c)| has_tone(c)).map(|(i, _)| i).collect();
    if pos.len() != 1 {
        return Style::Bad;
    }
    let b: Vec<char> = base.chars().collect();
    let (old, new, here) = (tone_index(&b, false), tone_index(&b, true), pos[0] as i32);
    match (old == new, here == old, here == new) {
        (true, true, _) => Style::Both,
        (false, true, _) => Style::Old,
        (false, false, true) => Style::New,
        _ => Style::Bad,
    }
}

// ------------------------------------------------------------------ vnfix: canonical forms
fn strip_marks(s: &str) -> String {
    s.to_lowercase().replace('đ', "d").nfd().filter(|&c| ccc(c) == 0).collect()
}
fn canon(s: &str) -> String {
    let (mut base, tone) = split_tone(s);
    if tone > 0 {
        base.push((b'0' + tone) as char);
    }
    base
}
/// canonical form ("hoa2") -> written form; keeps the tone position of `refw` when it is the same word
fn realize(c: &str, refw: Option<&str>) -> String {
    let tone = match c.chars().last().and_then(|l| l.to_digit(10)) {
        Some(t) if t > 0 => t as u8,
        _ => return c.to_string(),
    };
    let base = &c[..c.len() - 1];
    if let Some(r) = refw.filter(|r| !r.is_empty()) {
        let (rb, rt) = split_tone(r);
        if rb == base && rt > 0 {
            if let Some(i) = r.nfc().position(has_tone) {
                return put_mark(base, i as i32, tone);
            }
        }
    }
    let b: Vec<char> = base.chars().collect();
    put_mark(base, tone_index(&b, false), tone)
}

// ------------------------------------------------------------------ model + parameters
const KINDS: [&str; 4] = ["tone", "edit", "edit_rare", "context"];
const REASONS: [&str; 4] = ["Âm tiết không hợp quy tắc chính tả", "Âm tiết không hợp quy tắc chính tả (thiếu/thừa/nhầm chữ cái)",
    "Chữ hiếm gặp, gần với một chữ phổ biến", "Sai theo ngữ cảnh"];
const ALPHABET: &str = "abcdeghiklmnopqrstuvxy";

/// (start, end, old, new, kind, sure, mark, reason, gain, tier) – field order of vspell.Fix
type Fix = (usize, usize, String, String, &'static str, bool, bool, String, f64, u8);
/// (start, end, word, reason) – vspell.Suspect
type Sus = (usize, usize, String, String);
type Analysis = (Vec<Fix>, Vec<Sus>);

#[derive(Default)]
struct Grams {
    tri: HashMap<[u8; 3], u32>,
    bi: HashMap<[u8; 2], u32>,
}
impl Grams {
    fn add<'a>(&mut self, words: impl Iterator<Item = &'a str>) {
        for w in words {
            let b: Vec<u8> = [b'^', b'^'].into_iter().chain(w.bytes()).chain([b'$']).collect();
            for x in b.windows(3) {
                *self.tri.entry([x[0], x[1], x[2]]).or_default() += 1;
                *self.bi.entry([x[0], x[1]]).or_default() += 1;
            }
        }
    }
}

/// English-vs-Vietnamese word model of langid.py
#[derive(Default)]
struct Lang {
    en: HashMap<String, i64>,   // zipf×100
    kt: HashMap<String, i64>,   // letter frame -> frequency of valid Vietnamese syllables
    kn: HashMap<String, i64>,   // the part that is natively unaccented
    total: f64,
    g_en: Grams,
    g_vi: Grams,
    mu: f64,
    p_switch: f64,
    p_en0: f64,
    en_bias: f64,
    tri_k: f64,
    tiny: f64,
    max_syllable: usize,
    telex_prior: f64,
    delta: f64,
    en_protect: i64,
}

#[derive(Default)]
struct Params {
    p_tone: f64,
    p_edit: f64,
    p_edit_rare: f64,
    p_context: f64,
    invalid_cost: f64,
    ascii_extra: f64,
    oov_logp: f64,
    unk_logp: f64,
    thresh: [f64; 4],
    wide: [f64; 4],
    tone_ratio: i64,
    edit_max_orig: i64,
    edit_min_cand: i64,
    rare_count: i64,
    min_cand_count: i64,
    max_token: usize,
    keep_caps: bool,
    change_penalty: f64,
    degraded_factor: f64,
    max_cands: usize,
}

#[derive(Clone, Copy)]
struct State {
    id: Option<u32>,
    emit: f64,
    kind: Option<u8>, // None = the typed word itself
}

/// everything about a written word that does not depend on its neighbours; computed once per call
struct Word {
    text: String,
    low: String,
    n: usize,
    oid: Option<u32>,
    valid: bool,
    placement_bad: bool,
    never: bool, // kept as typed wherever it stands (one letter, too long, not Vietnamese letters, camelCase, abbreviation)
    cap: bool,
    orig: [State; 1],
    cands: OnceCell<Vec<State>>,
    lang: [OnceCell<(f64, f64)>; 2], // emission (log P vi, log P en) for [plain, accented] paragraphs
}
type Words = HashMap<String, Rc<Word>>;

struct Tok {
    start: usize,
    end: usize,
    w: Rc<Word>,
    skip: bool,
    en: bool, // recognised as English (langid.py)
}

#[pyclass(frozen)]
struct Speller {
    p: Params,
    words: Vec<String>,
    wid: HashMap<String, u32>,
    uni: Vec<i64>,
    logu: Vec<f64>,
    brow: Vec<u32>,  // bigram rows: pairs (a, b) are bnext[brow[a]..brow[a + 1]], sorted by b
    bnext: Vec<u32>,
    bcounts: Vec<u32>,
    lex_by_key: HashMap<String, Vec<u32>>, // spell candidates: valid syllables by letter frame
    ocr_by_key: HashMap<String, Vec<u32>>, // OCR candidates: every word by letter frame (top MAX_CANDS)
    degraded: Vec<bool>,
    pairs: Vec<Vec<char>>, // wrong spellings of PAIRS, longest first
    pair_map: HashMap<String, String>,
    lang: Option<Lang>,
    style_pairs: Vec<(String, String)>,
    dup_words: HashSet<String>,
}

fn word_spans(t: &[char]) -> Vec<(usize, usize)> {
    let (mut out, mut i) = (Vec::new(), 0);
    while i < t.len() {
        if is_tok(t[i]) {
            let s = i;
            while i < t.len() && is_tok(t[i]) {
                i += 1;
            }
            out.push((s, i));
        } else {
            i += 1;
        }
    }
    out
}
fn has_any(w: &[char], pat: &str) -> bool {
    let p: Vec<char> = pat.chars().collect();
    w.windows(p.len()).any(|x| x == p.as_slice())
}
/// regex `[/@\\]|www|http` (+ `\.(?:com|vn|gov|org|net)\b` when `tld`) on text[a-12 : b+12]
fn url_like(t: &[char], a: usize, b: usize, tld: bool) -> bool {
    let w = &t[a.saturating_sub(12)..(b + 12).min(t.len())];
    w.iter().any(|c| matches!(c, '/' | '@' | '\\'))
        || has_any(w, "www")
        || has_any(w, "http")
        || tld && (0..w.len()).any(|i| {
            w[i] == '.' && ["com", "vn", "gov", "org", "net"].iter().any(|d| {
                let e = i + 1 + d.len();
                e <= w.len() && w[i + 1..e].iter().copied().eq(d.chars()) && w.get(e).is_none_or(|&c| !is_w(c))
            })
        })
}
const VI_LOW: &str = "ăâđêôơưáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ";
const VI_UP: &str = "ĂÂĐÊÔƠƯÁÀẢÃẠẮẰẲẴẶẤẦẨẪẬÉÈẺẼẸẾỀỂỄỆÍÌỈĨỊÓÒỎÕỌỐỒỔỖỘỚỜỞỠỢÚÙỦŨỤỨỪỬỮỰÝỲỶỸỴ";
fn vi_low(c: char) -> bool {
    c.is_ascii_lowercase() || VI_LOW.contains(c)
}

impl Speller {
    fn trans(&self, a: Option<u32>, b: Option<u32>) -> f64 {
        match (a, b) {
            (_, None) => self.p.unk_logp,
            (None, Some(b)) => self.logu[b as usize],
            (Some(a), Some(b)) => {
                let (lo, hi) = (self.brow[a as usize] as usize, self.brow[a as usize + 1] as usize);
                match self.bnext[lo..hi].binary_search(&b) {
                    Ok(p) => (self.bcounts[lo + p] as f64 / self.uni[a as usize] as f64).ln(),
                    Err(_) => 0.4f64.ln() + self.logu[b as usize], // "stupid backoff"
                }
            }
        }
    }

    // -------------------------------------------------------------- vspell: tokens and candidate lattice
    fn word(&self, w: String, words: &mut Words) -> Rc<Word> {
        if let Some(x) = words.get(&w) {
            return x.clone();
        }
        let low = w.to_lowercase();
        let n = w.chars().count();
        let upper = is_upper_str(&w);
        let valid = valid_syllable(&low);
        let oid = self.wid.get(&canon(&low)).copied();
        let x = Rc::new(Word {
            never: n == 1
                || n > self.p.max_token
                || !looks_vietnamese(&low)
                || (w.chars().skip(1).any(|c| c.is_uppercase()) && !upper)
                || (upper && n >= 2 && !valid),
            placement_bad: valid && tone_style(&low) == Style::Bad,
            cap: is_cap(&w),
            orig: [State { id: oid, emit: 0.0, kind: None }],
            cands: OnceCell::new(),
            lang: [OnceCell::new(), OnceCell::new()],
            text: w.clone(),
            low, n, oid, valid,
        });
        words.insert(w, x.clone());
        x
    }

    fn tokenize(&self, t: &[char], words: &mut Words) -> Vec<Tok> {
        let mut toks: Vec<Tok> = Vec::new();
        let mut last_end = 0;
        for (s, e) in word_spans(t) {
            let w = self.word(s_of(&t[s..e]), words);
            let (after, after2) = (t.get(e).copied(), t.get(e + 1).copied());
            let gap = &t[last_end..s];
            let sent_start = toks.is_empty()
                || gap.iter().any(|c| matches!(c, '\n' | '\t' | '\x0c' | '\x0b'))
                || gap.iter().rev().find(|&&c| !is_space(c)).is_some_and(|c| ".!?:;".contains(*c));
            let skip = w.never
                || (s > 0 && (is_digit(t[s - 1]) || "-/_.@#&\\".contains(t[s - 1])))
                || after.is_some_and(|c| is_digit(c) || "-/_@#\\".contains(c))
                || (after == Some('.') && after2.is_some_and(is_alnum))
                || (self.p.keep_caps && w.cap && !sent_start && !w.valid); // proper / foreign names
            toks.push(Tok { start: s, end: e, w, skip, en: false });
            last_end = e;
        }
        toks
    }

    /// letter frames one edit away from `key` that exist in the vocabulary, in vspell.edit1_keys order
    fn edit1_keys(&self, key: &str) -> Vec<&Vec<u32>> {
        let k: Vec<char> = key.chars().collect();
        let n = k.len();
        let mut seen: HashSet<String> = HashSet::from([key.to_string()]);
        let mut out = Vec::new();
        let mut add = |cand: String| {
            if let Some(v) = self.lex_by_key.get(&cand) {
                if seen.insert(cand) {
                    out.push(v);
                }
            }
        };
        let join = |a: &[char], mid: &[char], b: &[char]| a.iter().chain(mid).chain(b).collect::<String>();
        for i in 0..n {
            add(join(&k[..i], &[], &k[i + 1..]));
        }
        for i in 0..=n {
            for c in ALPHABET.chars() {
                add(join(&k[..i], &[c], &k[i..]));
            }
        }
        for i in 0..n {
            for c in ALPHABET.chars().filter(|&c| c != k[i]) {
                add(join(&k[..i], &[c], &k[i + 1..]));
            }
        }
        for i in 0..n.saturating_sub(1) {
            if k[i] != k[i + 1] {
                add(join(&k[..i], &[k[i + 1], k[i]], &k[i + 2..]));
            }
        }
        out
    }

    /// candidate states of a word that may be corrected; the first one is the word as typed
    fn states<'a>(&self, t: &'a Tok) -> &'a [State] {
        if t.skip {
            return &t.w.orig;
        }
        t.w.cands.get_or_init(|| self.candidates(&t.w))
    }

    fn candidates(&self, t: &Word) -> Vec<State> {
        let p = &self.p;
        let mut out = t.orig.to_vec();
        let key = strip_marks(&t.low);
        let own = t.oid.map_or(0, |i| self.uni[i as usize]);
        let mut seen: HashSet<Option<u32>> = HashSet::from([t.oid]);
        let mut add = |i: u32, kind: u8, pen: f64| {
            if seen.insert(Some(i)) {
                out.push(State { id: Some(i), emit: -pen, kind: Some(kind) });
            }
        };
        let same = self.lex_by_key.get(&key).map_or(&[][..], |v| v.as_slice());
        let u = |i: u32| self.uni[i as usize];
        if t.valid {
            same.iter().take(6).for_each(|&i| add(i, 3, p.p_context));
            if own < p.rare_count && !t.placement_bad && !t.cap {
                for v in self.edit1_keys(&key) {
                    v.iter().take(4).for_each(|&i| add(i, 2, p.p_edit_rare));
                }
            }
            return out;
        }
        same.iter().take(8).filter(|&&i| u(i) >= p.tone_ratio * own).for_each(|&i| add(i, 0, p.p_tone));
        if own < p.edit_max_orig && !t.cap {
            for v in self.edit1_keys(&key) {
                v.iter().take(4).filter(|&&i| u(i) >= p.edit_min_cand).for_each(|&i| add(i, 1, p.p_edit));
            }
        }
        out
    }

    fn state_logp(&self, t: &Word, st: &State) -> f64 {
        match (st.kind, st.id) {
            (Some(_), Some(i)) => self.logu[i as usize] + st.emit,
            (_, Some(i)) if t.valid => self.logu[i as usize],
            (_, Some(i)) => self.logu[i as usize] - self.p.invalid_cost,
            (_, None) if t.valid => self.p.oov_logp,
            _ => self.p.unk_logp,
        }
    }

    /// Viterbi over one run of words (`sts`: their candidate states); `forced` pins word j to state k.
    /// Returns (score, path).
    fn decode(&self, seg: &[Tok], sts: &[&[State]], tr: &[Vec<Vec<f64>>], forced: Option<(usize, usize)>) -> (f64, Vec<usize>) {
        let ks = |j: usize| -> Vec<usize> {
            match forced {
                Some((fj, fk)) if fj == j => vec![fk],
                _ => (0..sts[j].len()).collect(),
            }
        };
        let mut prev: Vec<f64> = Vec::new();
        let mut back: Vec<Vec<usize>> = Vec::with_capacity(seg.len());
        for j in 0..seg.len() {
            let pks = if j > 0 { ks(j - 1) } else { vec![] };
            let (mut cur, mut bp) = (Vec::new(), Vec::new());
            for k in ks(j) {
                let u = self.state_logp(&seg[j].w, &sts[j][k]);
                let (mut best, mut arg) = (u, 0);
                for (pi, &sc) in prev.iter().enumerate() {
                    let s = sc + tr[j - 1][pks[pi]][k] + u;
                    if pi == 0 || s > best {
                        (best, arg) = (s, pi);
                    }
                }
                cur.push(best);
                bp.push(arg);
            }
            back.push(bp);
            prev = cur;
        }
        let mut at = 0;
        for (i, &x) in prev.iter().enumerate() {
            if x > prev[at] {
                at = i;
            }
        }
        let score = prev[at];
        let mut path = vec![0; seg.len()];
        for j in (0..seg.len()).rev() {
            path[j] = ks(j)[at];
            at = back[j][at];
        }
        (score, path)
    }

    fn context_fixes(&self, t: &[char], toks: &[Tok], fixes: &mut Vec<Fix>) -> Vec<Sus> {
        let all: Vec<&[State]> = toks.iter().map(|x| self.states(x)).collect();
        let first = fixes.len();
        let mut a = 0;
        while a < toks.len() {
            let mut b = a + 1;
            while b < toks.len() {
                let gap = &t[toks[b - 1].end..toks[b].start];
                if gap.len() > 3 || gap.iter().any(|&c| c != ' ' && c != '\t') {
                    break;
                }
                b += 1;
            }
            let (seg, sts) = (&toks[a..b], &all[a..b]);
            a = b;
            if sts.iter().all(|x| x.len() == 1) {
                continue;
            }
            let tr: Vec<Vec<Vec<f64>>> = sts
                .windows(2)
                .map(|w| w[0].iter().map(|x| w[1].iter().map(|y| self.trans(x.id, y.id)).collect()).collect())
                .collect();
            let (score, path) = self.decode(seg, sts, &tr, None);
            for (j, (tk, &k)) in seg.iter().zip(&path).enumerate() {
                let (Some(kind), Some(id)) = (sts[j][k].kind, sts[j][k].id) else { continue };
                let gain = score - self.decode(seg, sts, &tr, Some((j, 0))).0;
                let w = &tk.w;
                let new = apply_case(&w.text, &realize(&self.words[id as usize], Some(&w.low)));
                if new == w.text {
                    continue;
                }
                let kd = kind as usize;
                let extra = if w.text.is_ascii() && kd == 0 { self.p.ascii_extra } else { 0.0 };
                let tier = if gain >= self.p.thresh[kd] + extra { 2 } else if gain >= self.p.wide[kd] + extra { 1 } else { 0 };
                let gain = format!("{gain:.1}").parse().unwrap_or(gain);
                fixes.push((tk.start, tk.end, w.text.clone(), new, KINDS[kd], tier == 2, true, REASONS[kd].into(), gain, tier));
            }
        }
        let done: HashSet<usize> = fixes[first..].iter().map(|f| f.0).collect();
        toks.iter()
            .filter(|x| !x.skip && !x.w.valid && !done.contains(&x.start) && !x.w.text.is_ascii())
            .map(|x| (x.start, x.end, x.w.text.clone(), "Không phải âm tiết tiếng Việt".to_string()))
            .collect()
    }

    // -------------------------------------------------------------- langid: English words inside Vietnamese text
    fn logchar(g: &Grams, k: f64, w: &str) -> f64 {
        let (mut a, mut b, mut t) = (b'^', b'^', 0.0);
        for c in w.bytes().chain([b'$']) {
            let tri = g.tri.get(&[a, b, c]).copied().unwrap_or(0) as f64;
            let bi = g.bi.get(&[a, b]).copied().unwrap_or(0) as f64;
            t += ((tri + k) / (bi + k * 27.0)).ln();
            (a, b) = (b, c);
        }
        t
    }

    /// langid.emission: (log P(word | VI), log P(word | EN))
    fn emission(&self, l: &Lang, w: &Word, accented: bool) -> (f64, f64) {
        if w.n == 1 {
            return (0.0, 0.0);
        }
        let floor = l.tiny.ln();
        if !w.low.is_ascii() {
            return if looks_vietnamese(&w.low) { (0.0, floor) } else { (floor, 0.0) };
        }
        if accented && is_upper_str(&w.text) {
            return (floor, 0.0); // unaccented capitals inside an accented paragraph: BIF, DOI, UBND
        }
        let k = l.en.get(&w.low).copied();
        let pe = k.map_or(0.0, |k| 10f64.powf(k as f64 / 100.0 - 9.0));
        let ce = Self::logchar(&l.g_en, l.tri_k, &w.low).exp();
        let en = (((1.0 - l.mu) * pe + l.mu * ce).max(l.tiny)).ln() + l.en_bias;
        let kn = l.kn.get(&w.low).copied().unwrap_or(0);
        if accented && k.is_some_and(|k| k >= l.en_protect) && kn == 0 {
            return (floor, en);
        }
        let tel = telex_decode(&w.low);
        if tel.is_none() && (w.low.chars().count() > l.max_syllable || !looks_vietnamese(&w.low)) {
            return (floor, en);
        }
        let kt = l.kt.get(&w.low).copied().unwrap_or(0);
        let mut pv = (kn as f64 + if accented { l.delta } else { 1.0 } * (kt - kn) as f64) / l.total;
        if let Some(i) = tel.and_then(|t| self.wid.get(&canon(&t))) {
            pv += l.telex_prior * self.uni[*i as usize] as f64 / l.total;
        }
        let cv = Self::logchar(&l.g_vi, l.tri_k, &w.low).exp();
        ((((1.0 - l.mu) * pv + l.mu * cv).max(l.tiny)).ln(), en)
    }

    /// langid.english_flags: two-state Viterbi over the words of one paragraph
    fn mark_english(&self, toks: &mut [Tok]) {
        let Some(l) = &self.lang else { return };
        if toks.is_empty() {
            return;
        }
        let accented = toks.iter().any(|t| !t.w.text.is_ascii() && looks_vietnamese(&t.w.low));
        let em: Vec<(f64, f64)> =
            toks.iter().map(|t| *t.w.lang[accented as usize].get_or_init(|| self.emission(l, &t.w, accented))).collect();
        let (stay, mv) = ((1.0 - l.p_switch).ln(), l.p_switch.ln());
        let mut v = (1.0 - l.p_en0).ln() + em[0].0;
        let mut e = l.p_en0.ln() + em[0].1;
        let mut back: Vec<(u8, u8)> = Vec::with_capacity(toks.len());
        for x in &em[1..] {
            let (fv, fe) = (v + stay, e + mv);
            let (bv, nv) = if fe > fv { (1, fe) } else { (0, fv) };
            let (fv, fe) = (v + mv, e + stay);
            let (be, ne) = if fv > fe { (0, fv) } else { (1, fe) };
            (v, e) = (nv + x.0, ne + x.1);
            back.push((bv, be));
        }
        let mut st = (e > v) as u8;
        for i in (0..toks.len()).rev() {
            if st == 1 && toks[i].w.text.is_ascii() {
                toks[i].skip = true;
                toks[i].en = true;
            }
            if i > 0 {
                st = if st == 1 { back[i - 1].1 } else { back[i - 1].0 };
            }
        }
    }

    // -------------------------------------------------------------- vspell: leftover Telex keystrokes
    fn telex_fixes(&self, toks: &[Tok], fixes: &mut Vec<Fix>) {
        for tk in toks {
            let t = &tk.w;
            if t.valid || !(3..=9).contains(&t.n) || !t.text.is_ascii() || tk.en || (tk.skip && looks_vietnamese(&t.low))
                || is_upper_str(&t.text)
            {
                continue; // English words and unaccented capitals (BIF, DOS, ISO) are not leftover Telex
            }
            let Some(new) = telex_decode(&t.low) else { continue };
            let known = self.wid.get(&canon(&new)).is_some_and(|&i| self.uni[i as usize] >= 300);
            if !known || t.oid.is_some_and(|i| self.uni[i as usize] >= 5) {
                continue; // already a known word (teen, queen...): foreign, not Telex
            }
            fixes.push((tk.start, tk.end, t.text.clone(), apply_case(&t.text, &new), "telex", true, true,
                "Còn sót phím Telex".into(), 0.0, 2));
        }
    }

    // -------------------------------------------------------------- vspell: spacing, repeated words, known pairs
    fn tech_fixes(&self, t: &[char], fixes: &mut Vec<Fix>) {
        let n = t.len();
        let sp = |a: usize, b: usize, new: &str, why: &str| -> Fix {
            (a, b, s_of(&t[a..b]), new.to_string(), "space", true, false, why.to_string(), 0.0, 2)
        };
        let tok_at = |i: usize| t.get(i).is_some_and(|&c| is_tok(c));
        if !t.windows(3).any(|w| w == [' ', ' ', ' ']) {
            let mut i = 1;
            while i + 2 < n {
                if t[i] == ' ' && t[i + 1] == ' ' && (is_tok(t[i - 1]) || ",;:)".contains(t[i - 1])) && is_tok(t[i + 2]) {
                    fixes.push(sp(i, i + 2, " ", "Hai dấu cách liền nhau"));
                    i += 2;
                } else {
                    i += 1;
                }
            }
        }
        let mut i = 1;
        while i < n {
            if t[i] == ' ' && is_alnum(t[i - 1]) {
                let mut j = i;
                while j < n && t[j] == ' ' {
                    j += 1;
                }
                if j < n && ",;:!?".contains(t[j]) && t.get(j + 1).is_none_or(|&c| is_space(c) || ")\"”’»".contains(c)) {
                    fixes.push(sp(i, j, "", "Thừa dấu cách trước dấu câu"));
                }
                i = j;
            } else {
                i += 1;
            }
        }
        for i in 2..n {
            if ",;:".contains(t[i]) && tok_at(i - 1) && tok_at(i - 2) && tok_at(i + 1) && tok_at(i + 2) && !url_like(t, i, i + 1, true) {
                fixes.push(sp(i, i + 1, &format!("{} ", t[i]), "Thiếu dấu cách sau dấu câu"));
            }
        }
        for i in 2..n.saturating_sub(2) {
            if t[i] == '.'
                && vi_low(t[i - 1])
                && vi_low(t[i - 2])
                && (t[i + 1].is_ascii_uppercase() || VI_UP.contains(t[i + 1]))
                && (t[i + 2].is_ascii_lowercase() || "ăâđêôơư".contains(t[i + 2]))
                && !url_like(t, i, i + 1, false)
            {
                fixes.push(sp(i, i + 1, ". ", "Thiếu dấu cách sau dấu chấm"));
            }
        }
        // repeated function word: (?<!\w)(\w+)( +)\1(?!\w), case-insensitive
        let mut i = 0;
        while i < n {
            if !is_w(t[i]) {
                i += 1;
                continue;
            }
            let mut j = i;
            while j < n && is_w(t[j]) {
                j += 1;
            }
            let mut k = j;
            while k < n && t[k] == ' ' {
                k += 1;
            }
            let e = k + (j - i);
            if k > j && e <= n && (0..j - i).all(|x| eq_ci(t[i + x], t[k + x])) && !t.get(e).is_some_and(|&c| is_w(c)) {
                let w = s_of(&t[i..j]);
                if self.dup_words.contains(&w.to_lowercase()) {
                    fixes.push((i, e, s_of(&t[i..e]), w.clone(), "dup", true, true, format!("Lặp từ \"{w}\""), 0.0, 2));
                }
                i = e;
            } else {
                i = j;
            }
        }
    }

    fn pair_fixes(&self, t: &[char], fixes: &mut Vec<Fix>) {
        let n = t.len();
        let mut i = 0;
        while i < n {
            let hit = (i == 0 || !is_tok(t[i - 1])).then(|| self.pairs.iter().find_map(|pat| {
                if !eq_ci(t[i], pat[0]) {
                    return None;
                }
                let mut p = i;
                for &pc in pat {
                    if pc == ' ' {
                        if !t.get(p).is_some_and(|&c| is_space(c)) {
                            return None;
                        }
                        while p < n && is_space(t[p]) {
                            p += 1;
                        }
                    } else if t.get(p).is_some_and(|&c| eq_ci(c, pc)) {
                        p += 1;
                    } else {
                        return None;
                    }
                }
                (!t.get(p).is_some_and(|&c| is_tok(c))).then_some(p)
            }));
            let Some(Some(e)) = hit else {
                i += 1;
                continue;
            };
            let old = s_of(&t[i..e]);
            let key: String = old.to_lowercase().split(is_space).filter(|x| !x.is_empty()).collect::<Vec<_>>().join(" ").nfc().collect();
            if let Some(right) = self.pair_map.get(&key) {
                let new = apply_case(&old, right);
                if new != old {
                    fixes.push((i, e, old, new, "pair", true, true, "Cặp sai–đúng thường gặp".into(), 0.0, 2));
                }
            }
            i = e.max(i + 1);
        }
    }

    fn analyze_one(&self, text: &str, style: &str, use_context: bool, words: &mut Words) -> Analysis {
        let t: Vec<char> = text.chars().collect();
        let mut toks = self.tokenize(&t, words);
        self.mark_english(&mut toks);
        let mut fixes: Vec<Fix> = Vec::new();
        self.tech_fixes(&t, &mut fixes);
        self.pair_fixes(&t, &mut fixes);
        self.telex_fixes(&toks, &mut fixes);
        let new_style = style == "new";
        for tk in toks.iter().filter(|x| !x.skip && x.w.placement_bad) {
            let w = &tk.w;
            let (base, tone) = split_tone(&w.low);
            let low = place_tone(&base, tone, new_style);
            if low != w.low {
                fixes.push((tk.start, tk.end, w.text.clone(), apply_case(&w.text, &low), "placement", true, true,
                    "Dấu thanh đặt sai nguyên âm".into(), 0.0, 2));
            }
        }
        let mut suspects = if use_context { self.context_fixes(&t, &toks, &mut fixes) } else { vec![] };
        // overlaps: word fixes win over spacing fixes; within a class the earlier one stays
        let prio = |k: &str| match k {
            "pair" => 0,
            "telex" => 1,
            "placement" => 2,
            "tone" | "edit" => 3,
            "edit_rare" | "context" => 4,
            "dup" => 5,
            "style" => 6,
            "space" => 7,
            _ => 9,
        };
        fixes.sort_by_key(|f| (prio(f.4), f.0));
        let mut kept: Vec<Fix> = Vec::new();
        for f in fixes {
            if !kept.iter().any(|g| f.0 < g.1 && g.0 < f.1) {
                kept.push(f);
            }
        }
        kept.sort_by_key(|f| f.0);
        if new_style {
            for f in kept.iter_mut().filter(|f| matches!(f.4, "tone" | "edit" | "edit_rare" | "context" | "telex")) {
                f.3 = restyle_new(&f.3);
            }
        }
        suspects.retain(|s| !kept.iter().any(|f| s.0 < f.1 && f.0 < s.1));
        (kept, suspects)
    }

    // -------------------------------------------------------------- vnfix: OCR diacritic restoration
    fn ocr_correct(&self, text: &str, pen: f64) -> (String, Vec<(String, String, usize, usize)>) {
        let t: Vec<char> = text.chars().collect();
        let spans = word_spans(&t);
        let mut repl: Vec<(usize, usize, String, String)> = Vec::new();
        let mut a = 0;
        while a < spans.len() {
            let mut b = a + 1;
            while b < spans.len() && t[spans[b - 1].1..spans[b].0].iter().all(|&c| c == ' ' || c == '\t') {
                b += 1;
            }
            let seg = &spans[a..b];
            a = b;
            let lat: Vec<Vec<Option<u32>>> = seg.iter().map(|&(s, e)| self.ocr_states(&t, s, e)).collect();
            if lat.iter().all(|x| x.len() == 1) {
                continue;
            }
            let lp = |i: Option<u32>| i.map_or(self.p.unk_logp, |i| self.logu[i as usize]);
            let emit = |j: usize, k: usize| {
                if k == 0 {
                    return 0.0;
                }
                -pen * if lat[j][0].is_some_and(|o| self.degraded[o as usize]) { self.p.degraded_factor } else { 1.0 }
            };
            let mut prev: Vec<f64> = (0..lat[0].len()).map(|k| lp(lat[0][k]) + emit(0, k)).collect();
            let mut back: Vec<Vec<usize>> = Vec::new();
            for j in 1..lat.len() {
                let (mut cur, mut bp) = (Vec::new(), Vec::new());
                for (k, &st) in lat[j].iter().enumerate() {
                    let (mut best, mut arg) = (0.0, 0);
                    for (pi, &sc) in prev.iter().enumerate() {
                        let s = sc + self.trans(lat[j - 1][pi], st) + emit(j, k);
                        if pi == 0 || s > best {
                            (best, arg) = (s, pi);
                        }
                    }
                    cur.push(best);
                    bp.push(arg);
                }
                back.push(bp);
                prev = cur;
            }
            let mut at = 0;
            for (i, &x) in prev.iter().enumerate() {
                if x > prev[at] {
                    at = i;
                }
            }
            for j in (0..lat.len()).rev() {
                if let (true, Some(id)) = (at > 0, lat[j][at]) {
                    let old = s_of(&t[seg[j].0..seg[j].1]);
                    let new = apply_case(&old, &realize(&self.words[id as usize], Some(&old.to_lowercase())));
                    if new != old {
                        repl.push((seg[j].0, seg[j].1, new, old));
                    }
                }
                if j > 0 {
                    at = back[j - 1][at];
                }
            }
        }
        repl.sort_by_key(|r| r.0);
        let (mut out, mut fixes, mut last, mut len) = (String::new(), Vec::new(), 0, 0);
        for (s, e, new, old) in repl {
            out.extend(&t[last..s]);
            len += s - last;
            let n = new.chars().count();
            out.push_str(&new);
            fixes.push((old, new, len, len + n));
            len += n;
            last = e;
        }
        out.extend(&t[last..]);
        (out, fixes)
    }

    /// candidate ids for one OCR word; the first one is the word as read
    fn ocr_states(&self, t: &[char], s: usize, e: usize) -> Vec<Option<u32>> {
        let w = s_of(&t[s..e]);
        let low = w.to_lowercase();
        let oid = self.wid.get(&canon(&low)).copied();
        let (n, after) = (e - s, t.get(e).copied());
        let fixed = (is_upper_str(&w) && n <= 5 && oid.is_none())
            || n > 7
            || n == 1
            || (s > 0 && "-/._".contains(t[s - 1]))
            || after.is_some_and(|c| "-/_".contains(c))
            || (after == Some('.') && t.get(e + 1).is_some_and(|&c| is_alnum(c)));
        let mut out = vec![oid];
        if !fixed {
            if let Some(v) = self.ocr_by_key.get(&strip_marks(&low)) {
                out.extend(v.iter().filter(|&&i| Some(i) != oid).map(|&i| Some(i)));
            }
        }
        out
    }
}

fn restyle_new(word: &str) -> String {
    let (base, tone) = split_tone(&word.to_lowercase());
    if word.is_empty() || tone == 0 || !looks_vietnamese(&base) {
        return word.to_string();
    }
    apply_case(word, &place_tone(&base, tone, true))
}

/// one syllable typed in Telex but not converted (Vieejt -> việt, dduowcj -> được); input is lower case ASCII letters
fn telex_decode(s: &str) -> Option<String> {
    let c: Vec<char> = s.chars().collect();
    if c.is_empty() || !c.iter().all(|x| x.is_ascii_lowercase()) {
        return None;
    }
    let core = |body: &[char]| -> Option<(String, usize)> {
        let (mut out, mut i, mut sig) = (String::new(), 0, 0);
        while i < body.len() {
            let (x, nx) = (body[i], body.get(i + 1).copied());
            let two = match (x, nx) {
                ('d', Some('d')) => Some('đ'),
                ('a', Some('a')) => Some('â'),
                ('e', Some('e')) => Some('ê'),
                ('o', Some('o')) => Some('ô'),
                ('a', Some('w')) => Some('ă'),
                ('o', Some('w')) => Some('ơ'),
                ('u', Some('w')) => Some('ư'),
                _ => None,
            };
            match two {
                Some(ch) => {
                    out.push(ch);
                    i += 2;
                    sig += 1;
                }
                None if "wfjz".contains(x) => return None,
                None => {
                    out.push(x);
                    i += 1;
                }
            }
        }
        Some((out, sig))
    };
    let mut cands: Vec<(Vec<char>, u8)> = Vec::new();
    for p in 1..c.len() {
        let tone = match c[p] {
            's' => 1,
            'f' => 2,
            'r' => 3,
            'x' => 4,
            'j' => 5,
            _ => continue,
        };
        let coda = s_of(&c[p + 1..]);
        if "aeiouyw".contains(c[p - 1]) && ["", "c", "ch", "m", "n", "ng", "nh", "p", "t"].contains(&coda.as_str()) {
            cands.push(([&c[..p], &c[p + 1..]].concat(), tone));
        }
    }
    cands.push((c.clone(), 0));
    for (body, tone) in cands {
        let Some((out, sig)) = core(&body) else { continue };
        if sig + (tone > 0) as usize == 0 {
            continue;
        }
        let base = place_tone(&out.nfc().collect::<String>(), tone, false);
        if valid_syllable(&base) {
            return Some(base);
        }
    }
    None
}

fn le<const N: usize, T>(raw: &[u8], f: fn([u8; N]) -> T) -> Vec<T> {
    raw.chunks_exact(N).map(|c| f(c.try_into().unwrap())).collect()
}

#[pymethods]
impl Speller {
    /// words: vocabulary (canonical forms, most frequent first); uni/bkeys/bcounts: raw little-endian arrays of
    /// vnlm.zip; cfg: the tuning constants of vspell.py / vnfix.py (single source of truth stays in Python).
    #[new]
    #[pyo3(signature = (words, uni, bkeys, bcounts, cfg, en_tsv=None))]
    fn new(words: Vec<String>, uni: &[u8], bkeys: &[u8], bcounts: &[u8], cfg: &Bound<'_, PyDict>, en_tsv: Option<&[u8]>) -> PyResult<Self> {
        fn get<'py, T: FromPyObjectOwned<'py>>(cfg: &Bound<'py, PyDict>, k: &str) -> PyResult<T> {
            let v = cfg.get_item(k)?.ok_or_else(|| pyo3::exceptions::PyKeyError::new_err(k.to_string()))?;
            v.extract::<T>().map_err(Into::into)
        }
        let by_kind = |k: &str| -> PyResult<[f64; 4]> {
            let m: HashMap<String, f64> = get(cfg, k)?;
            Ok(KINDS.map(|x| m.get(x).copied().unwrap_or(0.0)))
        };
        let p = Params {
            p_tone: get(cfg, "P_TONE_INVALID")?,
            p_edit: get(cfg, "P_EDIT_INVALID")?,
            p_edit_rare: get(cfg, "P_EDIT_RARE")?,
            p_context: get(cfg, "P_CONTEXT")?,
            invalid_cost: get(cfg, "INVALID_COST")?,
            ascii_extra: get(cfg, "ASCII_EXTRA")?,
            oov_logp: get(cfg, "OOV_VALID_LOGP")?,
            unk_logp: get(cfg, "UNK_LOGP")?,
            thresh: by_kind("THRESH")?,
            wide: by_kind("WIDE")?,
            tone_ratio: get(cfg, "TONE_RATIO")?,
            edit_max_orig: get(cfg, "EDIT_MAX_ORIG")?,
            edit_min_cand: get(cfg, "EDIT_MIN_CAND")?,
            rare_count: get(cfg, "RARE_COUNT")?,
            min_cand_count: get(cfg, "MIN_CAND_COUNT")?,
            max_token: get(cfg, "MAX_TOKEN")?,
            keep_caps: get(cfg, "KEEP_CAPS")?,
            change_penalty: get(cfg, "CHANGE_PENALTY")?,
            degraded_factor: get(cfg, "DEGRADED_FACTOR")?,
            max_cands: get(cfg, "MAX_CANDS")?,
        };
        let uni = le(uni, i64::from_le_bytes);
        if uni.len() != words.len() {
            return Err(pyo3::exceptions::PyValueError::new_err("uni.bin không khớp words.json"));
        }
        let total = uni.iter().sum::<i64>() as f64;
        let logu: Vec<f64> = uni.iter().map(|&u| ((u + 1) as f64 / total).ln()).collect();
        let wid: HashMap<String, u32> = words.iter().enumerate().map(|(i, w)| (w.clone(), i as u32)).collect();

        let mut lex_by_key: HashMap<String, Vec<u32>> = HashMap::new();
        let mut ocr_by_key: HashMap<String, Vec<u32>> = HashMap::new();
        let mut key_total: HashMap<String, f64> = HashMap::new();
        for (i, w) in words.iter().enumerate() {
            let s = realize(w, None);
            if uni[i] >= p.min_cand_count && looks_vietnamese(&s) && valid_syllable(&s) {
                lex_by_key.entry(strip_marks(&s)).or_default().push(i as u32);
            }
            let k = strip_marks(w.trim_end_matches(['0', '1', '2', '3', '4', '5']));
            *key_total.entry(k.clone()).or_default() += uni[i] as f64;
            let v = ocr_by_key.entry(k).or_default();
            if v.len() < p.max_cands {
                v.push(i as u32);
            }
        }
        lex_by_key.values_mut().for_each(|v| v.sort_by_key(|&i| -uni[i as usize]));
        let degraded = words.iter().enumerate().map(|(i, w)| {
            !w.chars().last().is_some_and(is_digit) && strip_marks(w) == *w && (uni[i] as f64) < 0.05 * key_total[w]
        }).collect();

        // bkeys.bin: sorted a * 2^21 + b -> row offsets per a, and the b column
        let (mut brow, mut bnext) = (vec![0u32; words.len() + 1], Vec::with_capacity(bkeys.len() / 8));
        let mut last = -1;
        for k in le(bkeys, i64::from_le_bytes) {
            let (a, b) = ((k >> 21) as usize, (k & 0x1f_ffff) as u32);
            if a >= words.len() || k <= std::mem::replace(&mut last, k) {
                return Err(pyo3::exceptions::PyValueError::new_err("bkeys.bin không hợp lệ hoặc chưa sắp xếp"));
            }
            bnext.push(b);
            brow[a + 1] = bnext.len() as u32;
        }
        for a in 1..brow.len() {
            brow[a] = brow[a].max(brow[a - 1]);
        }
        let lang = match en_tsv {
            None => None,
            Some(raw) => {
                let mut l = Lang::default();
                for line in std::str::from_utf8(raw).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?.lines() {
                    if let Some((w, z)) = line.split_once('\t') {
                        l.en.insert(w.to_string(), z.parse().map_err(|_| pyo3::exceptions::PyValueError::new_err("words.tsv"))?);
                    }
                }
                for (i, w) in words.iter().enumerate() {
                    let s = realize(w, None);
                    if looks_vietnamese(&s) && valid_syllable(&s) {
                        let k = strip_marks(&s);
                        *l.kt.entry(k.clone()).or_default() += uni[i];
                        if s.is_ascii() {
                            *l.kn.entry(k).or_default() += uni[i];
                        }
                    }
                }
                let min_vi: i64 = get(cfg, "MIN_VI_KEY")?;
                l.g_en.add(l.en.keys().map(|k| k.as_str()));
                let vi: Vec<&str> = l.kt.iter().filter(|(k, &c)| c >= min_vi && !k.is_empty() && k.bytes().all(|b| b.is_ascii_lowercase()))
                    .map(|(k, _)| k.as_str()).collect();
                let mut g_vi = Grams::default();
                g_vi.add(vi.into_iter());
                l.g_vi = g_vi;
                l.total = total;
                l.mu = get(cfg, "MU")?;
                l.p_switch = get(cfg, "P_SWITCH")?;
                l.p_en0 = get(cfg, "P_EN0")?;
                l.en_bias = get(cfg, "EN_BIAS")?;
                l.tri_k = get(cfg, "TRI_K")?;
                l.tiny = get(cfg, "TINY")?;
                l.max_syllable = get(cfg, "MAX_SYLLABLE")?;
                l.telex_prior = get(cfg, "TELEX_PRIOR")?;
                l.delta = get(cfg, "DELTA")?;
                l.en_protect = get(cfg, "EN_PROTECT")?;
                Some(l)
            }
        };
        let pair_list: Vec<(String, String)> = get(cfg, "PAIRS")?;
        let mut pairs: Vec<Vec<char>> = pair_list.iter().map(|(k, _)| k.chars().collect()).filter(|k: &Vec<char>| !k.is_empty()).collect();
        pairs.sort_by_key(|k| std::cmp::Reverse(k.len()));
        Ok(Speller {
            p, words, wid, uni, logu,
            brow, bnext,
            bcounts: le(bcounts, u32::from_le_bytes),
            lex_by_key, ocr_by_key, degraded, pairs,
            pair_map: pair_list.into_iter().collect(),
            lang,
            style_pairs: get(cfg, "STYLE_PAIRS")?,
            dup_words: get(cfg, "DUP_WORDS")?,
        })
    }

    /// vspell._analyze for one paragraph (NFC text) -> (fixes, suspects)
    #[pyo3(signature = (text, style="old", use_context=true))]
    fn analyze(&self, py: Python<'_>, text: &str, style: &str, use_context: bool) -> Analysis {
        py.detach(|| self.analyze_one(text, style, use_context, &mut Words::new()))
    }

    /// analyze() for every paragraph of a document in one call, without holding the GIL
    #[pyo3(signature = (texts, style="old", use_context=true))]
    fn analyze_many(&self, py: Python<'_>, texts: Vec<String>, style: &str, use_context: bool) -> Vec<Analysis> {
        py.detach(|| {
            let mut words = Words::new();
            texts.iter().map(|t| self.analyze_one(t, style, use_context, &mut words)).collect()
        })
    }

    /// vspell.tone_style_of_document: "old" (hòa, thủy) or "new" (hoà, thuỷ), whichever is more frequent
    fn tone_style_of_document(&self, py: Python<'_>, texts: Vec<String>) -> &'static str {
        py.detach(|| {
            let (mut old, mut new) = (0, 0);
            let mut seen: HashMap<String, Style> = HashMap::new();
            for tx in &texts {
                let t: Vec<char> = tx.chars().collect();
                for (s, e) in word_spans(&t) {
                    let w = s_of(&t[s..e]).to_lowercase();
                    let n = w.chars().count();
                    if n < 3 || n > self.p.max_token {
                        continue;
                    }
                    let st = match seen.get(&w) {
                        Some(&st) => st,
                        None => *seen.entry(w.clone()).or_insert(tone_style(&w)),
                    };
                    old += (st == Style::Old) as usize;
                    new += (st == Style::New) as usize;
                }
            }
            if new > old { "new" } else { "old" }
        })
    }

    /// vspell.style_fixes: per paragraph, the spots to change so the document uses one spelling variant
    fn style_fixes(&self, py: Python<'_>, texts: Vec<String>) -> Vec<Vec<Fix>> {
        py.detach(|| {
            let docs: Vec<Vec<char>> = texts.iter().map(|t| t.chars().collect()).collect();
            let toks: Vec<Vec<(usize, usize, String)>> = docs
                .iter()
                .map(|t| word_spans(t).into_iter().map(|(s, e)| (s, e, s_of(&t[s..e]).to_lowercase())).collect())
                .collect();
            let mut counts: HashMap<&str, usize> = HashMap::new();
            for (_, _, w) in toks.iter().flatten() {
                *counts.entry(w).or_default() += 1;
            }
            let cnt = |w: &str| counts.get(w).copied().unwrap_or(0);
            let mut plan: HashMap<&str, &str> = HashMap::new();
            for (a, b) in &self.style_pairs {
                let (na, nb) = (cnt(a), cnt(b));
                if na > 0 && nb > 0 && na != nb {
                    let (from, to) = if na > nb { (b, a) } else { (a, b) };
                    plan.insert(from, to);
                }
            }
            let (mut old, mut new) = (0, 0);
            let mut forms: HashMap<&str, (Style, String)> = HashMap::new();
            for (&w, &c) in &counts {
                let n = w.chars().count();
                let st = tone_style(w);
                if n < 3 || n > self.p.max_token || !matches!(st, Style::Old | Style::New) {
                    continue;
                }
                let (base, tone) = split_tone(w);
                forms.insert(w, (st, place_tone(&base, tone, st == Style::Old)));
                if st == Style::Old { old += c } else { new += c }
            }
            let majority = (old > 0 && new > 0 && old != new).then_some(if old > new { Style::Old } else { Style::New });
            docs.iter().zip(&toks).map(|(t, ws)| {
                ws.iter().filter_map(|(s, e, w)| {
                    let tgt = plan.get(w.as_str()).copied().or_else(|| {
                        let (st, other) = forms.get(w.as_str())?;
                        (majority.is_some_and(|m| m != *st) && cnt(other) > 0).then_some(other.as_str())
                    })?;
                    let old = s_of(&t[*s..*e]);
                    (tgt != w).then(|| (*s, *e, old.clone(), apply_case(&old, tgt), "style", true, true,
                        "Thống nhất cách viết trong văn bản".to_string(), 0.0, 2))
                }).collect()
            }).collect()
        })
    }

    /// vnfix.correct_text -> (corrected text, [(from, to, start, end)] with positions in the corrected text)
    #[pyo3(signature = (text, penalty=None))]
    fn ocr_correct_text(&self, py: Python<'_>, text: &str, penalty: Option<f64>) -> (String, Vec<(String, String, usize, usize)>) {
        py.detach(|| self.ocr_correct(text, penalty.unwrap_or(self.p.change_penalty)))
    }

    /// vnfix.suspicious_spans: words unknown to the vocabulary that still look Vietnamese
    fn ocr_suspicious_spans(&self, text: &str) -> Vec<(usize, usize)> {
        let t: Vec<char> = text.chars().collect();
        word_spans(&t).into_iter().filter(|&(s, e)| {
            let w = s_of(&t[s..e]);
            let low = w.to_lowercase();
            e - s >= 2 && !(is_upper_str(&w) && e - s <= 5) && !self.wid.contains_key(&canon(&low))
                && self.ocr_by_key.contains_key(&strip_marks(&low))
        }).collect()
    }
}

/// (letters, letters that are upper case or have no case) – what roles/extract need to tell ALL-CAPS text
#[pyfunction]
fn alpha_caps(s: &str) -> (usize, usize) {
    s.chars().filter(|&c| is_alpha(c)).fold((0, 0), |(n, up), c| {
        let mut u = c.to_uppercase();
        (n + 1, up + (u.next() == Some(c) && u.next().is_none()) as usize)
    })
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Speller>()?;
    m.add_function(wrap_pyfunction!(alpha_caps, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))
}

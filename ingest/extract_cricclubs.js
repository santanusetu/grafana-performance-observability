// Extract NACL Div A scorecards from CricClubs into one JSON file.
//
// CricClubs sits behind Cloudflare, so a plain HTTP client is blocked. Run this in the
// browser console on any cricclubs.com/nacltennisballcricket page, while signed in:
//
//   1. Set LEAGUE_ID (Summer 2026 - A = 68, Spring 2026 - A = 60) and LEAGUE_NAME.
//   2. Paste the script. It fetches every scorecard and over-by-over page slowly
//      (one match every ~5 s) to stay polite and avoid the bot check.
//   3. Progress is kept in localStorage, so it can be re-run after a Cloudflare check.
//   4. When done it downloads <OUT_FILE>; move it into data/ and run ingest/load.py.

const LEAGUE_ID = 68;
const LEAGUE_NAME = 'Summer 2026 - A';
const OUT_FILE = 'nacl-diva-summer2026.json';
const CLUB = 27594;
const BASE = '/nacltennisballcricket';
const KEY = `_league${LEAGUE_ID}`;

const clean = el => el.textContent.trim().replace(/\s+/g, ' ');
const sleep = ms => new Promise(r => setTimeout(r, ms));
const parse = html => new DOMParser().parseFromString(html, 'text/html');

async function matchIds() {
  const d = parse(await fetch(`${BASE}/listMatches.do?league=${LEAGUE_ID}&clubId=${CLUB}`).then(r => r.text()));
  return [...new Set([...d.querySelectorAll('a')]
    .map(a => (a.getAttribute('href') || '').match(/matchId=(\d+)/))
    .filter(Boolean).map(m => m[1]))];
}

async function scorecard(id) {
  const d = parse(await fetch(`${BASE}/viewScorecard.do?matchId=${id}&clubId=${CLUB}`).then(r => r.text()));
  await sleep(1800);
  const e = parse(await fetch(`${BASE}/overbyoverscoreview.do?matchId=${id}&clubId=${CLUB}`).then(r => r.text()));
  if (d.title.startsWith('Just') || e.title.startsWith('Just')) throw new Error('cloudflare check');

  const body = clean(d.body);
  const m = {
    match_id: +id,
    stage: d.title.split(':')[0],
    title: d.title.replace(' - NACL Tennis Ball Cricket', ''),
    date: (body.match(/\d\d\/\d\d\/\d{4}/) || [''])[0],
    result: ((body.match(/\S[^.]{0,60}? won by \d+ (Runs?|Wickets?)/i) ||
              body.match(/Super Over\.\s*Winner:\s*[^.]+?(?= Admin| Captain|$)/) ||
              body.match(/It is a Tie/i) || [''])[0]).replace(/^.*?ov /, ''),
    innings: [],
    over_by_over: [],
  };

  const tables = [...d.querySelectorAll('table')];
  tables.forEach((t, i) => {
    const cap = clean(t.rows[0] || t);
    if (!/innings/.test(cap) || t.rows[0].cells.length <= 4) return;
    const inn = { team: cap.split(' innings')[0], total: '', extras: '', batting: [], bowling: [] };
    for (const r of [...t.rows].slice(1)) {
      const c = [...r.cells].map(clean);
      if (/^Extras/.test(c[0])) inn.extras = c.join(' ');
      else if (/^Total/.test(c[0])) inn.total = c.join(' ');
      else if (c.length >= 7) inn.batting.push({ name: c[0].replace(c[1], '').trim(), dismissal: c[1],
        runs: +c[2], balls: +c[3], fours: +c[4], sixes: +c[5] });
    }
    for (let j = i + 1; j < tables.length && j < i + 4; j++) {
      if (!/^Bowling/.test(clean(tables[j].rows[0]))) continue;
      inn.bowling = [...tables[j].rows].slice(1).map(r => [...r.cells].map(clean).slice(1)).map(b => ({
        name: b[0], overs: b[1], maidens: +b[2], dots: +b[3], runs: +b[4], wickets: +b[5], econ: +b[6],
        extras_note: b[7] || '' }));
      break;
    }
    m.innings.push(inn);
  });

  m.over_by_over = [...e.querySelectorAll('table')].slice(1).map(t => ({
    batting_team: clean(t.rows[0]).replace(/ Batting$/, ''),
    overs: [...t.rows].slice(2).map(r => [...r.cells].map(clean))
      .map(c => ({ over: +c[0], bowler_and_balls: c[1], runs: +c[2], score: c[3] })),
  }));
  return m;
}

(async () => {
  const ids = await matchIds();
  const have = JSON.parse(localStorage.getItem(KEY) || '[]');
  const got = new Set(have.map(x => String(x.match_id)));
  for (const id of ids) {
    if (got.has(id)) continue;
    have.push(await scorecard(id));
    localStorage.setItem(KEY, JSON.stringify(have));
    console.log(`fetched ${have.length} of ${ids.length}`);
    await sleep(3000);
  }
  // Matches with no play (0/0) or abandoned are left for load.py's validation to report.
  const out = { source: 'cricclubs.com/nacltennisballcricket', league: LEAGUE_NAME, league_id: LEAGUE_ID,
                club_id: CLUB, extracted_at: new Date().toISOString(), match_count: have.length, matches: have };
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 1)], { type: 'application/json' }));
  a.download = OUT_FILE;
  a.click();
  localStorage.removeItem(KEY);
})();

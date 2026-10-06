-- Astros Analytics: raw scorecard tables.
-- The `raw` schema holds player-level data and is readable only by the owner.
-- Grafana's read-only role (grafana_reader) reads team-level views in `cricket`.

CREATE SCHEMA IF NOT EXISTS raw;
REVOKE ALL ON SCHEMA raw FROM PUBLIC;

CREATE TABLE IF NOT EXISTS raw.matches (
    match_id      integer PRIMARY KEY,
    league        text        NOT NULL,
    stage         text        NOT NULL,          -- 'League' | 'Quarter Final' | ...
    match_date    date        NOT NULL,
    team_bat1     text        NOT NULL,          -- batted first
    team_bat2     text        NOT NULL,          -- batted second
    winner        text,                          -- NULL = no result
    margin_text   text,                          -- e.g. 'won by 27 Runs'
    tied          boolean     NOT NULL DEFAULT false,
    super_over    boolean     NOT NULL DEFAULT false,
    result_text   text        NOT NULL
);

CREATE TABLE IF NOT EXISTS raw.innings (
    match_id      integer     NOT NULL REFERENCES raw.matches ON DELETE CASCADE,
    innings_no    smallint    NOT NULL CHECK (innings_no IN (1, 2)),
    batting_team  text        NOT NULL,
    bowling_team  text        NOT NULL,
    runs          integer     NOT NULL,
    wickets       smallint    NOT NULL,
    legal_balls   smallint    NOT NULL,          -- overs converted to balls
    extras_b      smallint    NOT NULL,
    extras_lb     smallint    NOT NULL,
    extras_w      smallint    NOT NULL,
    extras_nb     smallint    NOT NULL,
    PRIMARY KEY (match_id, innings_no)
);

CREATE TABLE IF NOT EXISTS raw.batting (
    match_id       integer    NOT NULL,
    innings_no     smallint   NOT NULL,
    position       smallint   NOT NULL,
    player         text       NOT NULL,
    dismissal_text text       NOT NULL,
    dismissal_type text       NOT NULL,          -- caught|bowled|run_out|stumped|lbw|not_out|other
    runs           smallint   NOT NULL,
    balls          smallint   NOT NULL,
    fours          smallint   NOT NULL,
    sixes          smallint   NOT NULL,
    PRIMARY KEY (match_id, innings_no, position),
    FOREIGN KEY (match_id, innings_no) REFERENCES raw.innings ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS raw.bowling (
    match_id       integer    NOT NULL,
    innings_no     smallint   NOT NULL,          -- the innings being bowled at
    spell_no       smallint   NOT NULL,
    player         text       NOT NULL,
    legal_balls    smallint   NOT NULL,
    maidens        smallint   NOT NULL,
    dots           smallint   NOT NULL,
    runs           smallint   NOT NULL,
    wickets        smallint   NOT NULL,
    wides          smallint   NOT NULL,
    noballs        smallint   NOT NULL,
    PRIMARY KEY (match_id, innings_no, spell_no),
    FOREIGN KEY (match_id, innings_no) REFERENCES raw.innings ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS raw.overs (
    match_id       integer    NOT NULL,
    innings_no     smallint   NOT NULL,
    over_no        smallint   NOT NULL CHECK (over_no BETWEEN 1 AND 20),
    runs           smallint   NOT NULL,          -- runs in this over
    cum_runs       smallint   NOT NULL,
    cum_wickets    smallint   NOT NULL,
    wickets        smallint   NOT NULL,          -- wickets in this over
    phase          text       GENERATED ALWAYS AS (
                       CASE WHEN over_no <= 6 THEN 'powerplay'
                            WHEN over_no <= 15 THEN 'middle'
                            ELSE 'death' END) STORED,
    PRIMARY KEY (match_id, innings_no, over_no),
    FOREIGN KEY (match_id, innings_no) REFERENCES raw.innings ON DELETE CASCADE
);

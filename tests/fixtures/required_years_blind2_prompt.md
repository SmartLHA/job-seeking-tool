# Prompt used to write `required_years_blind2.json` (2026-11-07)

This is the exact instruction given to the agent that wrote the second blind set. It is
saved so that anyone can check how the set was made (acceptance criterion B2 in
`docs/tasks/2026-11-06-required-years-search-jobs-design.md`, section 18).

---

GOAL: Write one blind test-data file of synthetic UK job advert text, labelled with the
years of experience each advert truly requires of the candidate.

WHY: A text extractor that reads "required years of experience" from adverts will be
measured once on this file. The data must be written blind, by someone who has not seen
the extractor or any earlier test data, so the result is honest.

HARD LIMITS:
- Do NOT read anything under `src/`, `tests/` (other than writing the one output file),
  `archive/`, or any file whose name contains `required_years` other than this prompt.
  Do NOT look at how any extractor works. Do NOT open `.env`, `data/` or `output/`.
- All text is invented. No real employers, recruiters or people, and no copied adverts.
  Invent company names.
- Write only the one output file. Do not commit. Do not edit anything else.

OUTPUT FILE: `tests/fixtures/required_years_blind2.json` in the working directory.

FORMAT: a JSON list of objects:
`{"id": "b001", "group": "...", "text": "...", "min": <number or null>, "max": <number or null>, "note": "short reason"}`
- `min` and `max` are the years of experience the advert truly asks of the candidate. A
  single figure such as "5+ years" has min 5 and max null. A range such as "3-5 years" has
  min 3 and max 5. If the advert states no requirement in years for the candidate, or
  says the years are only desirable or nice to have, both are null.
- If an advert gives more than one required figure, label the highest lower bound that is
  a firm requirement.
- Label as a careful human reader would. A screening question such as "Do you have 5+
  years of experience in X?" counts as asking for 5.
- Months ("18 months' experience") and vague phrases ("several years", "extensive
  experience") count as no stated years: null.

CONTENT: 100 entries. UK IT, business analysis, project and programme management, data,
software, infrastructure and some non-IT roles. Use UK spelling and the varied styles real
UK adverts use: direct employers, recruitment agencies writing about "our client",
graduate and returner programmes, public sector, consultancies. Make every entry's wording
different; do not reuse sentence templates.
- group `short_requirement` (15): a 2-5 sentence excerpt stating a real requirement in years.
- group `short_trap` (20): a 2-5 sentence excerpt with a number followed by "year" or
  "years" that is NOT a requirement on the candidate. Include at least 5 boasts in which
  a named company or agency describes its own years of experience or history (for example
  "With over N years' experience in ... , <Company> is ..."). Also use other things real
  adverts say: company or brand age, age limits, security-clearance residency, contract
  or programme length, apprenticeships, benefits and long-service awards, data retention,
  team experience, career-progression timelines.
- group `short_mixed` (10): an excerpt holding both a trap and a real requirement, in
  either order.
- group `short_none` (5): an excerpt with no number of years at all.
- group `full_advert` (50): a full advert of 1,500 to 4,000 characters with the usual
  structure (about the company, role summary, responsibilities, requirements, benefits),
  using line breaks and bullet lines. Place any requirement where a real advert would.
  At least 15 of the 50 state no requirement in years. At least 15 contain a trap,
  including at least 5 named-company or agency boasts.

ACCEPTANCE: run `python3 -I -c` to load the file and print the count per group, the
character-length range of `full_advert` entries, the number of entries with `min` null in
each group, whether ids are unique, whether every entry has all fields, and whether
`min <= max` wherever both are set. The counts must match the above. Paste that output.

REPORT: conclusions first (10 lines at most), the pasted check output, then
`FILES_WRITTEN:` with the path, then a final line
`STATUS: DONE|PARTIAL|BLOCKED — <reason>`, plus what you did NOT check.

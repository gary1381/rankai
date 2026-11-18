# Write 48 new search queries for a job / gig / collaboration search engine

You are writing a held-out test set. Do not open any other folder, do not search the web, do not look at any
search results. Write what real people would type into a search box when looking for work or collaborators.

Write the file `queries_v1.jsonl` in this folder: exactly 48 lines, one JSON object per line:
`{"id": "hzh01", "lang": "zh", "query": "..."}`
- ids `hzh01`–`hzh16` (lang `zh`): written in Chinese. English technical terms may appear where a Chinese
  speaker would naturally use them (e.g. "Python", "SaaS"), but the sentence is Chinese.
- ids `hen01`–`hen16` (lang `en`): English.
- ids `hmix01`–`hmix16` (lang `mix`): Chinese and English mixed in one query, as bilingual people type.

Within EACH language (16 queries), cover:
- at least 5 full-time jobs, 2 part-time, 2 contract / freelance, 2 internships, 2 outsourcing projects
  (外包 / a project to hand off), 1 open-source bounty or paid issue, 1 co-founder / partner search;
- at least 5 queries that ask for remote work, at least 3 that name a city, country or region,
  at least 2 that state a minimum pay (any currency, per month or per year);
- at least 5 queries for roles that are NOT software engineering (design, marketing, sales, support, operations,
  finance, recruiting, content, research, teaching, etc.);
- a range of lengths: some 2–4 words, some full sentences with several requirements.

Rules:
- Do not repeat or lightly reword any query in `existing_queries_do_not_repeat.jsonl` (same role with the same
  constraints counts as a repeat). New roles and new combinations are the point.
- No personal names, no email addresses, no phone numbers. Company names are allowed but at most 2 per language.
- Keep each query under 80 characters.

When finished, also write `DONE.txt` containing the single word `done`.

# Top of the Year — Stremio catalog

Stremio home-screen rows: **Top Movies/Series of the Year** and **All-Time Great Movies/Series**,
across every streaming service.

- Data: IMDb's public daily datasets (`title.ratings`, `title.basics`). No API key.
- Ranking: IMDb weighted rating, so a title needs many votes to rank high
  (movies ≥ 25k votes, series ≥ 10k). Early in the year the list is topped up with last year's titles.
- Rebuilt daily by GitHub Actions and served by GitHub Pages.

Install in Stremio: `https://farhat7.github.io/stremio-top-of-year/manifest.json`

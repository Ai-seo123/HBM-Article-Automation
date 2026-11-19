/**
 * Yoast analysis sidecar.
 *
 * Runs Yoast's own `yoastseo` package so the plugin/backend can get a real SEO and
 * readability score, plus the list of failing assessments, before a post is
 * ever created. Yoast has no PHP/Python analyser, which is why this exists.
 *
 * Run it next to WordPress/FastAPI backend:
 *   npm install
 *   BCWP_SECRET=some-long-random-string node server.js
 *
 * Then set the URL and the same secret in the backend .env (BCWP_SECRET).
 *
 * NOTE: yoastseo's internal module paths move between major versions. The
 * package.json here pins a version known to expose these entry points. If you
 * upgrade and the require() calls throw, check the package's exports and adjust
 * the three requires below. Everything else in this file is stable.
 */

const express = require("express");
const { Paper, ContentAssessor, SeoAssessor, interpreters } = require("yoastseo");

// Researchers are per-language. English covers most agency work; add more by
// requiring the matching languageProcessing/languages/<code>/Researcher.
const EnglishResearcher = require("yoastseo/build/languageProcessing/languages/en/Researcher").default;

const app = express();
app.use(express.json({ limit: "4mb" }));

const SECRET = process.env.BCWP_SECRET || "";
const PORT = process.env.PORT || 3939;

// Health check endpoint (public for Render deployment liveness probes & backend ping)
app.get("/health", (req, res) => res.json({ ok: true, service: "yoast-sidecar" }));

// Security middleware: strictly authenticates all other endpoints
app.use((req, res, next) => {
  if (!SECRET) {
    return res.status(500).json({ error: "Server misconfiguration: BCWP_SECRET is not configured." });
  }
  if (req.get("X-BCWP-Secret") !== SECRET) {
    return res.status(403).json({ error: "forbidden" });
  }
  next();
});

app.post("/analyze", (req, res) => {
  const {
    content = "",
    keyphrase = "",
    title = "",
    description = "",
    slug = "",
    permalink = "",
    locale = "en_US",
    date = "",
  } = req.body || {};

  if (!content || !keyphrase) {
    return res.status(400).json({ error: "content and keyphrase are required" });
  }

  try {
    const paper = new Paper(content, {
      keyword: keyphrase,
      title: title,
      titleWidth: measureTitleWidth(title),
      description: description,
      slug: slug,
      permalink: permalink,
      locale: locale,
      date: date,
    });

    const researcher = new EnglishResearcher(paper);

    const seoAssessor = new SeoAssessor(researcher, { locale });
    seoAssessor.assess(paper);

    const contentAssessor = new ContentAssessor(researcher, { locale });
    contentAssessor.assess(paper);

    const seoScore = seoAssessor.calculateOverallScore();
    const readScore = contentAssessor.calculateOverallScore();

    res.json({
      seo: {
        score: seoScore,
        rating: rate(seoScore),
        results: collect(seoAssessor),
      },
      readability: {
        score: readScore,
        rating: rate(readScore),
        results: collect(contentAssessor),
      },
    });
  } catch (err) {
    console.error("analysis failed", err);
    res.status(500).json({ error: String(err && err.message ? err.message : err) });
  }
});

/**
 * Pull the individual assessment results out of an assessor.
 * Each carries a 0-9 score; under 6 is what keeps the bullet off green.
 */
function collect(assessor) {
  return assessor
    .getValidResults()
    .map((result) => ({
      id: typeof result.getIdentifier === "function" ? result.getIdentifier() : "",
      score: result.getScore(),
      text: stripTags(result.getText()),
    }))
    .sort((a, b) => a.score - b.score);
}

function rate(score) {
  try {
    return interpreters.scoreToRating(score / 10);
  } catch (e) {
    if (score >= 71) return "good";
    if (score >= 41) return "ok";
    return "bad";
  }
}

function stripTags(html) {
  return String(html || "")
    .replace(/<[^>]*>/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Yoast measures title width in pixels, not characters. This is a rough
 * approximation that is close enough for the title-width assessment.
 */
function measureTitleWidth(title) {
  return Math.round(String(title).length * 8.5);
}

app.listen(PORT, () => {
  console.log(`Yoast analyzer listening on ${PORT}${SECRET ? " (secured)" : " (NO SECRET SET)"}`);
});

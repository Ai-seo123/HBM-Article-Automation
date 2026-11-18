# Yoast SEO Analyzer Sidecar

Node.js microservice that executes Yoast's official `yoastseo` package for pre-publishing SEO and readability scoring in the HBM Article Automation platform.

## Overview

Because Yoast SEO's analysis engine is written in JavaScript (`yoastseo`), this lightweight Express sidecar evaluates HTML content, focus keyphrases, titles, meta descriptions, and slugs. It calculates official Yoast SEO and readability scores (0-100) and returns granular assessments before any draft is pushed to WordPress.

## Requirements

- Node.js >= 18.0.0
- npm or pnpm

## Installation

```bash
cd yoast-sidecar
npm install
```

## Configuration

Copy `.env.example` to `.env`:

```bash
PORT=3939
BCWP_SECRET=your-yoast-shared-secret-here
```

| Variable | Description | Default |
|---|---|---|
| `PORT` | Listening port for the HTTP sidecar | `3939` |
| `BCWP_SECRET` | Shared secret token passed via `X-BCWP-Secret` header | `""` |

## Running the Service

### Development / Direct
```bash
node server.js
```

### Production / Render
```bash
npm start
```

## API Endpoints

### 1. Health Check
- **Endpoint**: `GET /health`
- **Headers**: None required
- **Response**: `{"ok": true}`

### 2. Analyze Article
- **Endpoint**: `POST /analyze`
- **Headers**:
  - `Content-Type: application/json`
  - `X-BCWP-Secret: <BCWP_SECRET>`
- **Request Body**:
```json
{
  "content": "<p>Article HTML content...</p>",
  "keyphrase": "focus keyword",
  "title": "Article Title",
  "description": "Meta description...",
  "slug": "article-slug",
  "permalink": "https://homebusinessmag.com/article-slug/",
  "locale": "en_US",
  "date": "2026-11-17"
}
```
- **Response**:
```json
{
  "seo": {
    "score": 85,
    "rating": "good",
    "results": [ ... ]
  },
  "readability": {
    "score": 75,
    "rating": "good",
    "results": [ ... ]
  }
}
```

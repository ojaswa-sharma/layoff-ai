# GitHub App Commit Processing Service

This service processes GitHub commits via webhooks and provides historical backfill when a GitHub App is installed.

## Features

### Real-time Processing
- Processes commits from GitHub push webhooks in real-time
- Fetches commit diffs using GitHub App authentication
- Analyzes commits with AI and stores results

### Historical Backfill
- Automatically triggers when GitHub App is installed (`installation.created` event)
- Fetches historical commits with pagination support
- Respects GitHub API rate limits with retry logic
- Idempotent: skips commits that already exist

## Configuration

### Environment Variables

- `APP_ID`: GitHub App ID
- `GITHUB_PEM_PATH`: Path to GitHub App private key PEM file (default: `isometrik.pem`)
- `MONGO_URL`: MongoDB connection string
- `OPENAI_KEY`: OpenAI API key for commit analysis
- `BACKFILL_MAX_COMMITS`: (Optional) Maximum commits to backfill per repository
- `BACKFILL_MAX_DAYS`: (Optional) Maximum days of history to backfill

## Webhook Endpoints

### POST `/github/webhook`

Handles GitHub webhook events:

- **Push events**: Processes commits in real-time
- **Installation events**: 
  - `installation.created`: Triggers historical backfill
  - `installation.deleted`: Marks repositories as deleted

## Data Models

### Repository
Tracks repository sync status:
- `sync_status`: `BACKFILLING`, `LIVE`, or `FAILED`
- `backfill_started_at`, `backfill_completed_at`: Timestamps
- `total_commits_backfilled`: Progress counter

### Commit
Stores commit data with unique constraint on `(repository_name, commit_hash, installation_id)` to ensure idempotency.

## Architecture

- **Idempotency**: Unique indexes prevent duplicate commits
- **Race condition handling**: Webhooks received during backfill are processed safely
- **Error handling**: Retries with exponential backoff for GitHub API calls
- **Rate limiting**: Respects GitHub API rate limits with automatic retry
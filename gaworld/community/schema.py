"""Community-owned records; immutable versions and attachments commit together."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS community_drafts(
 id TEXT PRIMARY KEY, author_id INTEGER NOT NULL, publication_id TEXT NOT NULL,
 revision TEXT NOT NULL, content TEXT NOT NULL, published_version INTEGER, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS community_publications(
 id TEXT PRIMARY KEY, author_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'published',
 current_version INTEGER NOT NULL DEFAULT 0, locked INTEGER NOT NULL DEFAULT 0, featured INTEGER NOT NULL DEFAULT 0,
 created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS community_versions(
 publication_id TEXT NOT NULL, version INTEGER NOT NULL, content TEXT NOT NULL,
 checksum TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(publication_id,version));
CREATE TABLE IF NOT EXISTS community_holds(publication_id TEXT PRIMARY KEY, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS community_posts(
 id TEXT PRIMARY KEY, author_id INTEGER NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
 category TEXT NOT NULL, publication_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'published',
 locked INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS community_comments(
 id TEXT PRIMARY KEY, author_id INTEGER NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
 version INTEGER NOT NULL DEFAULT 0, parent_id TEXT NOT NULL DEFAULT '', body TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'published', created_at REAL NOT NULL, edited_at REAL);
CREATE INDEX IF NOT EXISTS community_thread ON community_comments(target_type,target_id,created_at);
CREATE TABLE IF NOT EXISTS community_comment_edits(
 id INTEGER PRIMARY KEY, comment_id TEXT NOT NULL, body TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS community_bookmarks(
 user_id INTEGER NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL, created_at REAL NOT NULL,
 PRIMARY KEY(user_id,target_type,target_id));
CREATE TABLE IF NOT EXISTS community_notifications(
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
 message TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS community_reports(
 id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
 reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', resolution TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS community_actions(
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, target_type TEXT NOT NULL, target_id TEXT NOT NULL,
 action TEXT NOT NULL, reason TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS community_public_list ON community_publications(status,created_at);
INSERT OR IGNORE INTO community_holds SELECT id,created_at FROM community_publications WHERE status='hidden';
CREATE INDEX IF NOT EXISTS community_inbox ON community_notifications(user_id,created_at);
"""

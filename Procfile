release: alembic upgrade head || echo "alembic skipped (first deploy may need manual stamp head)"
web: python -m scripts.migrate_blobs_to_disk

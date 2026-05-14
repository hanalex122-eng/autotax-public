"""baseline — mevcut prod schema'yı temsil eder

İlk Alembic revision'ı. Boş upgrade/downgrade. Anlamı: "prod DB'de
tüm tablolar zaten var (init_db ile yaratıldı). Alembic'in başlangıç
noktası burası — bundan sonraki migration'lar gerçek değişiklik
yapacak."

Production'da bir kerelik şu komut çalıştırılır (Procfile release ile
otomatik):

    alembic upgrade head

İlk çalışmada `alembic_version` tablosunu oluşturur ve bu revision'ı
"applied" olarak işaretler. Hiçbir DDL çalışmaz çünkü upgrade() boş.

Sonraki migration'lar normal akış:
    alembic revision -m "açıklama"
    # ... op.add_column, op.create_index, vb. yaz ...
    git commit / push
    Railway deploy → release: alembic upgrade head → otomatik uygula.

NOT: db.py:init_db içindeki manuel ALTER blokları KALIYOR
(defense-in-depth). Alembic bir migration'ı atlasa bile init_db
idempotent IF NOT EXISTS pattern'iyle şema'yı tutarlı tutar.

Revision ID: 001_baseline
Revises:
Create Date: 2026-05-14 18:00:00
"""

from __future__ import annotations

# revision identifiers, used by Alembic.
revision = "001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Boş — baseline. Prod DB'sinde tüm tablolar zaten var."""
    pass


def downgrade() -> None:
    """Boş — baseline'ın altı yok."""
    pass

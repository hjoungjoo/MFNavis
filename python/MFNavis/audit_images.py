"""Check whether catalog POSS images are available on the image CDN."""

import sqlite3
from contextlib import closing

import requests
from tqdm import tqdm

from PiFinder import utils


def get_image_names() -> list[str]:
    """Read the current catalog database schema without changing the database."""
    with closing(
        sqlite3.connect(f"{utils.pifinder_db.resolve().as_uri()}?mode=ro", uri=True)
    ) as conn:
        rows = conn.execute(
            "SELECT DISTINCT image_name FROM object_images WHERE image_name != ''"
        ).fetchall()
    return [row[0] for row in rows]


def check_object_image(session: requests.Session, image_name: str) -> bool:
    filename = f"{image_name}_POSS.jpg"
    url = (
        "https://ddbeeedxfpnp0.cloudfront.net/catalog_images/"
        f"{image_name[-1]}/{filename}"
    )
    try:
        response = session.head(url, timeout=15)
        return response.status_code == 200
    except requests.RequestException:
        return False


def main() -> int:
    image_names = get_image_names()
    print(f"Checking {len(image_names)} catalog images...")
    missing = 0
    with requests.Session() as session:
        for image_name in tqdm(image_names):
            if not check_object_image(session, image_name):
                print(f"Unavailable: {image_name}")
                missing += 1
    print(f"Audit complete: {missing} unavailable of {len(image_names)}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())

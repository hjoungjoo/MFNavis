#!/usr/bin/python
# -*- coding:utf-8 -*-
"""
This script runs to fetch
images from AWS
"""

import os
import sys
import tempfile
from io import BytesIO

import requests
from PIL import Image
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

from PiFinder import cat_images
from PiFinder.gen_images import cached_image_exists
from PiFinder.db.objects_db import ObjectsDatabase


def check_missing_images() -> List[str]:
    """
    Efficiently check which images need to be fetched by working directly
    with image names from the database instead of creating CompositeObjects.

    Returns list of missing image names.
    """
    objects_db = ObjectsDatabase()
    try:
        _, cursor = objects_db.get_conn_cursor()
        # Get all image names directly from object_images table.
        cursor.execute(
            "SELECT DISTINCT image_name FROM object_images WHERE image_name != ''"
        )
        image_names = [row["image_name"] for row in cursor.fetchall()]
    finally:
        objects_db.close()

    missing_images = []
    for image_name in tqdm(image_names, desc="Checking existing images"):
        # Check if POSS image exists (primary check)
        poss_path = (
            f"{cat_images.BASE_IMAGE_PATH}/{image_name[-1]}/{image_name}_POSS.jpg"
        )
        sdss_path = (
            f"{cat_images.BASE_IMAGE_PATH}/{image_name[-1]}/{image_name}_SDSS.jpg"
        )
        if not cached_image_exists(poss_path) or not cached_image_exists(sdss_path):
            missing_images.append(image_name)

    return missing_images


def download_image_from_url(
    session: requests.Session, url: str, file_path: str
) -> Tuple[bool, str]:
    """
    Download a single image using provided session.

    Returns (success, error_message)
    """
    try:
        response = session.get(url, timeout=30)
        if response.status_code == 200:
            with Image.open(BytesIO(response.content)) as image:
                if image.format != "JPEG":
                    return False, "Response is not a JPEG"
                image.verify()
            directory = os.path.dirname(file_path)
            os.makedirs(directory, exist_ok=True)
            fd, temporary = tempfile.mkstemp(
                prefix=".mfnavis-image-", suffix=".jpg", dir=directory
            )
            try:
                with os.fdopen(fd, "wb") as output:
                    output.write(response.content)
                os.replace(temporary, file_path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return True, ""
        elif response.status_code == 403:
            return False, "Not available (403)"
        else:
            return False, f"HTTP {response.status_code}"
    except Exception as e:
        return False, f"Error: {str(e)}"


def fetch_images_for_object(
    session: requests.Session, image_name: str
) -> Tuple[str, bool, List[str]]:
    """
    Fetch both POSS and SDSS images for a given image name.

    Returns (image_name, success, error_messages)
    """
    errors = []
    seq_ones = image_name[-1]  # Last character for directory

    # Download POSS image
    poss_filename = f"{image_name}_POSS.jpg"
    poss_path = f"{cat_images.BASE_IMAGE_PATH}/{seq_ones}/{poss_filename}"
    poss_url = f"https://ddbeeedxfpnp0.cloudfront.net/catalog_images/{seq_ones}/{poss_filename}"

    poss_success, poss_error = (
        (True, "exists")
        if cached_image_exists(poss_path)
        else download_image_from_url(session, poss_url, poss_path)
    )
    if not poss_success:
        errors.append(f"POSS: {poss_error}")

    # Download SDSS image
    sdss_filename = f"{image_name}_SDSS.jpg"
    sdss_path = f"{cat_images.BASE_IMAGE_PATH}/{seq_ones}/{sdss_filename}"
    sdss_url = f"https://ddbeeedxfpnp0.cloudfront.net/catalog_images/{seq_ones}/{sdss_filename}"

    sdss_success, sdss_error = (
        (True, "exists")
        if cached_image_exists(sdss_path)
        else download_image_from_url(session, sdss_url, sdss_path)
    )
    sdss_unavailable = sdss_error == "Not available (403)"
    if not sdss_success and not sdss_unavailable:
        errors.append(f"SDSS: {sdss_error}")

    overall_success = poss_success and (sdss_success or sdss_unavailable)

    return image_name, overall_success, errors


def download_images_concurrent(image_names: List[str], max_workers: int = 10) -> int:
    """
    Download images concurrently using ThreadPoolExecutor.

    Args:
        image_names: List of image names to download
        max_workers: Maximum number of concurrent downloads
    """
    if not image_names:
        return 0

    # Create a session for connection pooling
    session = requests.Session()
    session.headers.update({"User-Agent": "MFNavis-ImageDownloader/1.0"})

    failed_downloads = []

    executor = ThreadPoolExecutor(max_workers=max_workers)
    try:
        # Submit all download tasks
        future_to_image = {
            executor.submit(fetch_images_for_object, session, image_name): image_name
            for image_name in image_names
        }

        # Process completed downloads with progress bar
        for future in tqdm(
            as_completed(future_to_image),
            total=len(image_names),
            desc="Downloading images",
        ):
            image_name = future_to_image[future]
            try:
                image_name, success, errors = future.result()
                if not success and errors:
                    failed_downloads.append((image_name, errors))
            except Exception as exc:
                failed_downloads.append((image_name, [f"Exception: {exc}"]))
    except KeyboardInterrupt:
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)
    finally:
        session.close()

    # Report failed downloads
    if failed_downloads:
        print(f"\nFailed to download {len(failed_downloads)} objects:")
        for image_name, errors in failed_downloads[:10]:  # Show first 10 failures
            print(f"  {image_name}: {', '.join(errors)}")
        if len(failed_downloads) > 10:
            print(f"  ... and {len(failed_downloads) - 10} more")

    return len(failed_downloads)


def main() -> int:
    """
    Main function to check for and download missing catalog images.
    """
    cat_images.create_catalog_image_dirs()

    print("Checking for missing images...")
    missing_images = check_missing_images()

    if len(missing_images) > 0:
        print(f"Found {len(missing_images)} objects with missing images")
        print("Starting concurrent download...")
        failed = download_images_concurrent(missing_images, max_workers=10)
        if failed:
            return 1
        print("Download complete!")
    else:
        print("All images already downloaded!")
    return 0


if __name__ == "__main__":
    sys.exit(main())

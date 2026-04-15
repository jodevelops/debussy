#!/usr/bin/env python3
"""
Generate synthetic test data for E2E testing.

This script creates realistic (but fake) GLAM data:
  - CSV with museum collection structure
  - Synthetic images (colored squares with text overlay)
  - Simple PDF (text only, for testing text extraction)

Run once, then run E2E tests:
  python scripts/generate_e2e_testdata.py
  PYTHONPATH=src pytest tests/test_e2e_realistic.py -v
"""

from __future__ import annotations

import random
from pathlib import Path

import pandas as pd


def generate_csv(output_path: Path, num_rows: int = 1000):
    """Generate synthetic museum collection CSV."""
    random.seed(42)

    people = [
        "Albert Einstein", "Maria Curie", "Leonardo da Vinci",
        "Frida Kahlo", "Pablo Picasso", "Salvador Dalí",
        "Andy Warhol", "Joan Miró", "Jackson Pollock",
    ]
    places = [
        "Berlin", "Paris", "London", "Rome", "Vienna",
        "Amsterdam", "Florence", "Munich", "Barcelona",
    ]
    categories = ["painting", "sculpture", "photograph", "textile", "ceramic"]

    data = {
        "record_id": [f"REC-{i:05d}" for i in range(num_rows)],
        "title": [
            f"{random.choice(people)} - {random.choice(categories).title()}"
            for _ in range(num_rows)
        ],
        "description": [
            f"A {random.choice(categories)} from {random.choice(places)}, "
            f"circa {random.randint(1800, 2020)}."
            for _ in range(num_rows)
        ],
        "artist": [random.choice(people) if random.random() > 0.2 else None for _ in range(num_rows)],
        "date": [
            f"{random.randint(1800, 2020)}-{random.randint(1, 12):02d}"
            if random.random() > 0.3 else None
            for _ in range(num_rows)
        ],
        "location": [
            random.choice(places) if random.random() > 0.4 else ""
            for _ in range(num_rows)
        ],
        "material": [
            random.choice(["oil on canvas", "bronze", "ceramic", "photograph"])
            for _ in range(num_rows)
        ],
        "condition": [
            random.choice(["excellent", "good", "fair", "poor"])
            for _ in range(num_rows)
        ],
    }

    df = pd.DataFrame(data)
    df.to_csv(output_path, index=False)
    print(f"✓ Generated {output_path}: {num_rows} rows")


def generate_images(output_dir: Path, num_images: int = 10):
    """Generate synthetic images."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("⚠ PIL not installed, skipping image generation")
        print("  Install: pip install Pillow")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    random.seed(42)

    for i in range(num_images):
        # Random size (200-800 px)
        size = random.randint(200, 800)

        # Random color
        color = (random.randint(50, 255), random.randint(50, 255), random.randint(50, 255))

        # Create image
        img = Image.new("RGB", (size, size), color)
        draw = ImageDraw.Draw(img)

        # Add text
        text = f"Image {i+1}\nTest Data"
        try:
            draw.text((10, 10), text, fill=(255, 255, 255))
        except Exception:
            pass  # Font issue, skip text

        # Save
        path = output_dir / f"sample_{i+1:02d}.jpg"
        img.save(path, "JPEG")
        print(f"✓ Generated {path} ({size}x{size}px)")


def generate_pdf(output_path: Path):
    """Generate synthetic PDF."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except ImportError:
        print("⚠ reportlab not installed, skipping PDF generation")
        print("  Install: pip install reportlab")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(str(output_path), pagesize=letter)
    width, height = letter

    # 10 pages with text
    for page_num in range(1, 11):
        c.drawString(50, height - 50, f"Page {page_num}")
        c.drawString(50, height - 100, f"Sample PDF for Testing — {page_num*100} words")
        c.drawString(50, height - 150, "Albert Einstein was born in 1879 in Berlin, Germany.")
        c.drawString(50, height - 200, "He worked at the University of Berlin and Princeton.")
        c.drawString(50, height - 250, "The Nobel Prize in Physics was awarded to him in 1921.")
        c.showPage()

    c.save()
    print(f"✓ Generated {output_path}: 10 pages")


def main():
    """Generate all test data."""
    base_dir = Path(__file__).parent.parent / "tests" / "data" / "e2e"
    base_dir.mkdir(parents=True, exist_ok=True)

    print("\n📊 Generating E2E Test Data\n")

    # CSV
    generate_csv(base_dir / "subjects_restructured_1.csv", num_rows=1000)

    # Images
    generate_images(base_dir / "sample_images", num_images=10)

    # PDF
    generate_pdf(base_dir / "sample.pdf")

    print("\n✅ Test data ready in tests/data/e2e/")
    print("\nRun tests with:")
    print("  PYTHONPATH=src pytest tests/test_e2e_realistic.py -v\n")


if __name__ == "__main__":
    main()

"""Image processing utilities for QC Studio.

This module provides functions for creating and manipulating image montages.
"""

from pathlib import Path
from PIL import Image

from .data_loaders import _load_image_from_file


def create_grid_montage(images, padding=10, bg_color=(255, 255, 255), max_rows=None, max_cols=None):
    """Create a grid montage of images with aspect ratio close to 1 (square).

    Arranges multiple images in a grid layout optimized for square aspect ratio.
    All images are resized to the same dimensions for consistent layout.

    Args:
            images: List of PIL.Image objects or file paths (str/Path) to images.
                            Supported formats: SVG, PNG, JPG, JPEG.
                            Can mix PIL Images and file paths in the same list.
            padding: Padding (in pixels) between images and around the border (default: 10)
            bg_color: RGB tuple for background/padding color (default: white)
            max_rows: Maximum number of rows in grid (default: None for auto-calculate).
                              If set, limits grid to this many rows.
            max_cols: Maximum number of columns in grid (default: None for auto-calculate).
                              If set, limits grid to this many columns.

    Returns:
            PIL.Image: Montage image combining all input images in grid layout

    Raises:
            ValueError: If images list is empty or file loading fails

    Example:
            >>> from PIL import Image
            >>> # Using PIL Images
            >>> img1 = Image.open('image1.png')
            >>> img2 = Image.open('image2.png')
            >>> montage = create_grid_montage([img1, img2])
            >>>
            >>> # Using file paths (mix of SVG and raster)
            >>> montage = create_grid_montage(['plot1.svg', 'plot2.png', 'plot3.jpg'])
            >>>
            >>> # With custom grid constraints
            >>> montage = create_grid_montage([img1, img2, img3, img4], max_rows=2, max_cols=2)
    """
    if not images:
        raise ValueError("images list cannot be empty")

    # Load all images, converting file paths to PIL Images as needed
    loaded_images = []
    for img_input in images:
        if isinstance(img_input, Image.Image):
            # Already a PIL Image
            if img_input.mode != "RGB":
                img_input = img_input.convert("RGB")
            loaded_images.append(img_input)
        elif isinstance(img_input, (str, Path)):
            # File path - load and convert if necessary
            try:
                img = _load_image_from_file(img_input)
                loaded_images.append(img)
            except ValueError as e:
                print(f"Error loading image {img_input}: {e}")
                raise
        else:
            raise ValueError(f"Invalid image input: {type(img_input)}. " f"Expected PIL.Image or file path (str/Path)")

    images = loaded_images

    # Find target size for individual images (use max dimensions from all images)
    max_width = max(img.width for img in images)
    max_height = max(img.height for img in images)

    # Calculate optimal grid dimensions for aspect ratio close to 1
    # considering both the number of images AND their inherent aspect ratio
    num_images = len(images)

    best_rows = 1
    best_cols = num_images
    best_ratio_diff = abs(((best_cols * max_width) / (best_rows * max_height)) - 1)

    # Define the range of columns to search
    # If max_cols is specified, limit search to that value
    col_range_max = max_cols if max_cols else num_images
    col_range_max = min(col_range_max, num_images)  # Can't have more cols than images

    # Try different grid arrangements
    for test_cols in range(1, col_range_max + 1):
        test_rows = (num_images + test_cols - 1) // test_cols

        # Skip if exceeds max_rows constraint
        if max_rows and test_rows > max_rows:
            continue

        # Calculate what the final montage aspect ratio would be
        # (ignoring padding for simplicity as it's usually small)
        montage_aspect_ratio = (test_cols * max_width) / (test_rows * max_height)
        ratio_diff = abs(montage_aspect_ratio - 1)

        if ratio_diff < best_ratio_diff:
            best_ratio_diff = ratio_diff
            best_rows = test_rows
            best_cols = test_cols

    rows, cols = best_rows, best_cols
    # print(f"Creating {rows}x{cols} grid montage for {num_images} images (montage ratio diff: {best_ratio_diff:.3f})")

    # Resize all images to uniform size
    resized_images = []
    for img in images:
        if img.mode != "RGB":
            img = img.convert("RGB")
        if img.width != max_width or img.height != max_height:
            img = img.resize((max_width, max_height), Image.Resampling.LANCZOS)
        resized_images.append(img)

    # Calculate total montage dimensions
    total_width = cols * max_width + (cols + 1) * padding
    total_height = rows * max_height + (rows + 1) * padding

    # Create montage background
    montage = Image.new("RGB", (total_width, total_height), bg_color)

    # Place images in grid
    for idx, img in enumerate(resized_images):
        row = idx // cols
        col = idx % cols
        x = col * max_width + (col + 1) * padding
        y = row * max_height + (row + 1) * padding
        montage.paste(img, (x, y))

    return montage

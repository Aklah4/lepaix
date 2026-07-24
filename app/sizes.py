"""Size option sets, chosen by product category.

Footwear is sold in numeric sizes and apparel in letter sizes, so the admin
form and the storefront both ask this module which set a category uses instead
of hardcoding XS–XXL.
"""

LETTER_SIZES = ['XS', 'S', 'M', 'L', 'XL', 'XXL']

# EU numbering, wide enough to cover both women's and men's footwear. Anything
# outside it (half sizes, UK/US numbering) goes in the custom sizes field.
FOOTWEAR_SIZES = [str(n) for n in range(35, 47)]

# Matched against the category name, lowercased. Categories are free text the
# admin creates, so match on substrings rather than an exact list.
FOOTWEAR_KEYWORDS = (
    'shoe', 'sandal', 'slipper', 'slide', 'sneaker', 'trainer', 'boot',
    'heel', 'loafer', 'footwear', 'flip flop', 'flip-flop',
)


def is_footwear(category):
    """True when a category name reads like footwear (shoes, sandals, …)."""
    name = (category or '').lower()
    return any(word in name for word in FOOTWEAR_KEYWORDS)


def size_options(category):
    """The quick-pick sizes offered for a category."""
    return FOOTWEAR_SIZES if is_footwear(category) else LETTER_SIZES


def parse_sizes(checked, custom):
    """Merge checked boxes with the free-text field, in order, without repeats.

    `custom` is the raw comma-separated string from the form.
    """
    merged = []
    for size in list(checked) + [s.strip() for s in (custom or '').split(',')]:
        if size and size not in merged:
            merged.append(size)
    return merged

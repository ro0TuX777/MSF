def get_products():
    """
    Returns a static list of products for the catalog.
    No PII, no auth, no sensitive data.
    """
    return [
        {"id": 1, "name": "Standard Widget", "price": 10.0},
        {"id": 2, "name": "Premium Widget", "price": 20.0}
    ]

def detect_hotel_chain_from_url(url: str) -> str:
    url_lower = url.lower()

    if "hilton.com" in url_lower:
        return "hilton"
    elif "hyatt.com" in url_lower:
        return "hyatt"
    else:
        raise ValueError("Unsupported hotel chain in URL")

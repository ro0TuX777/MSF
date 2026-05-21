def get_system_health():
    """
    Returns internal system health metrics.
    Read-only, non-sensitive, no PII.
    """
    return {
        "cpu_usage": "15%",
        "memory_usage": "24%",
        "disk_space": "55%"
    }

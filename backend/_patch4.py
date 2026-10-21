def patch(path, pairs, enc="utf-8"):
    s = open(path, encoding=enc, newline="").read()
    for old, new in pairs:
        assert s.count(old) == 1, (path, old[:60], s.count(old))
        s = s.replace(old, new)
    open(path, "w", encoding=enc, newline="").write(s)

nl = "\r\n" if b"\r\n" in open("app/config.py", "rb").read() else "\n"
block = """    # Local LLM trading signal (Ollama). Paused by default: ~15s/ticker made scans overrun
    # their interval, and the quant algorithms carry the trading decision. When True it
    # still only runs during market hours. The advisor chat is unaffected.
    llm_signal_enabled: bool = False

    # Autonomous trading""".replace("\n", nl)
patch("app/config.py", [("    # Autonomous trading", block)], enc="cp1252")

patch("app/services/quant_engine/signal_combiner.py", [
("    llm_online = market_open and await llm_alive()",
 "    from app.config import settings as _settings\n    llm_online = _settings.llm_signal_enabled and market_open and await llm_alive()")])

patch("app/api/v1/advisor.py", [
("from app.services.advisor import llm_signal\n", "from app.config import settings\nfrom app.services.advisor import llm_signal\n"),
('        "market_open": _market_is_open(),   # the LLM trading signal only runs while True',
 '        "market_open": _market_is_open(),   # the LLM trading signal only runs while True\n        "signal_enabled": settings.llm_signal_enabled,')])

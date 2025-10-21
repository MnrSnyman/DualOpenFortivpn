"""Generate simple SVG mockups for documentation."""

from __future__ import annotations

from pathlib import Path
from string import Template

SVG_TEMPLATE = Template("""<svg xmlns='http://www.w3.org/2000/svg' width='1280' height='720' viewBox='0 0 1280 720'>
  <defs>
    <linearGradient id='bg' x1='0%' y1='0%' x2='0%' y2='100%'>
      <stop offset='0%' stop-color='#1f2430'/>
      <stop offset='100%' stop-color='#15181f'/>
    </linearGradient>
    <style>
      .title { font: 48px "DejaVu Sans", sans-serif; fill: #eef2f7; }
      .subtitle { font: 24px "DejaVu Sans", sans-serif; fill: #98a3b3; }
      .card-title { font: 26px "DejaVu Sans", sans-serif; fill: #eef2f7; }
      .card-body { font: 20px "DejaVu Sans", sans-serif; fill: #c9d1dd; }
      .badge { font: 20px "DejaVu Sans", sans-serif; fill: #62a0ea; }
      .button { font: 22px "DejaVu Sans", sans-serif; fill: #1f2430; }
    </style>
  </defs>
  <rect width='1280' height='720' fill='url(#bg)' rx='32'/>
  <text x='60' y='90' class='title'>OpenFortiVPN Manager</text>
  <text x='60' y='130' class='subtitle'>Dashboard · Inspired by Uptime Kuma</text>
  $cards
  $buttons
</svg>
""")

CARD_TEMPLATE = """<g>
  <rect x='{x}' y='{y}' width='520' height='220' rx='28' fill='#2d3341'/>
  <text x='{tx}' y='{ty}' class='card-title'>{name}</text>
  <text x='{tx}' y='{ty2}' class='badge'>{status}</text>
  <text x='{tx}' y='{ty3}' class='card-body'>{detail}</text>
  <text x='{tx}' y='{ty4}' class='card-body'>{iface}</text>
  <text x='{tx}' y='{ty5}' class='card-body'>{extra}</text>
</g>"""

BUTTON_TEMPLATE = """<g>
  <rect x='{x}' y='600' width='180' height='56' rx='16' fill='#62a0ea'/>
  <text x='{tx}' y='635' text-anchor='middle' class='button'>{label}</text>
</g>"""

PROFILES = [
    ("Engineering VPN", "🟢 Connected", "IP 10.1.2.3", "Interface ppp0", "RX 125 MB / TX 22 MB"),
    ("Support Tunnel", "🟠 Reconnecting", "Retry in 14s", "Interface ppp1", "Auto reconnect enabled"),
    ("Finance VPN", "🔴 Disconnected", "Last used 2h ago", "Interface ppp2", "SAML"),
    ("QA Lab", "🟢 Connected", "IP 172.16.0.8", "Interface ppp3", "Routes: lab/*"),
]

BUTTONS = ["Connect", "Disconnect", "View Logs", "Settings"]


def draw_cards() -> str:
    cards = []
    positions = [
        (60, 160),
        (660, 160),
        (60, 400),
        (660, 400),
    ]
    for (x, y), profile in zip(positions, PROFILES):
        cards.append(
            CARD_TEMPLATE.format(
                x=x,
                y=y,
                tx=x + 40,
                ty=y + 60,
                ty2=y + 105,
                ty3=y + 140,
                ty4=y + 175,
                ty5=y + 210,
                name=profile[0],
                status=profile[1],
                detail=profile[2],
                iface=profile[3],
                extra=profile[4],
            )
        )
    return "\n".join(cards)


def draw_buttons() -> str:
    buttons = []
    for idx, label in enumerate(BUTTONS):
        x = 60 + idx * 220
        buttons.append(BUTTON_TEMPLATE.format(x=x, tx=x + 90, label=label))
    return "\n".join(buttons)


def main() -> None:
    svg_content = SVG_TEMPLATE.substitute(cards=draw_cards(), buttons=draw_buttons())
    root = Path(__file__).resolve().parents[2]
    output = root / "assets" / "mockups" / "dashboard.svg"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(svg_content, encoding="utf-8")


if __name__ == "__main__":
    main()


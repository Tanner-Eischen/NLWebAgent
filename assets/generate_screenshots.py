"""Generate terminal-style screenshots for documentation."""
from PIL import Image, ImageDraw, ImageFont
import os

# Terminal colors (GitHub dark theme inspired)
BG_COLOR = "#0d1117"
TEXT_COLOR = "#c9d1d9"
ACCENT_COLOR = "#58a6ff"
GREEN_COLOR = "#3fb950"
YELLOW_COLOR = "#d29922"
GRAY_COLOR = "#8b949e"
BORDER_COLOR = "#30363d"

# Font settings - use monospace
FONT_SIZE = 14
LINE_HEIGHT = 20


def get_font():
    """Get a monospace font, falling back to default if needed."""
    font_paths = [
        "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/CascadiaMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ]
    for path in font_paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, FONT_SIZE)
    return ImageFont.load_default()


def create_terminal_screenshot(title: str, content: str, output_path: str, width: int = 800):
    """Create a terminal-style screenshot."""
    font = get_font()

    # Calculate dimensions
    lines = content.split('\n')
    padding = 20
    title_bar_height = 35

    # Calculate height needed
    content_height = len(lines) * LINE_HEIGHT + padding * 2
    total_height = title_bar_height + content_height

    # Create image
    img = Image.new('RGB', (width, total_height), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Draw title bar
    draw.rectangle([(0, 0), (width, title_bar_height)], fill="#161b22")
    draw.line([(0, title_bar_height), (width, title_bar_height)], fill=BORDER_COLOR, width=1)

    # Draw window controls (circles)
    draw.ellipse([(15, 12), (27, 24)], fill="#ff5f56")
    draw.ellipse([(35, 12), (47, 24)], fill="#ffbd2e")
    draw.ellipse([(55, 12), (67, 24)], fill="#27c93f")

    # Draw title
    draw.text((80, 10), title, fill=GRAY_COLOR, font=font)

    # Draw content
    y = title_bar_height + padding
    for line in lines:
        # Colorize certain parts
        if line.strip().startswith('$'):
            draw.text((padding, y), line, fill=GREEN_COLOR, font=font)
        elif '✅' in line or 'PASSED' in line:
            draw.text((padding, y), line, fill=GREEN_COLOR, font=font)
        elif '❌' in line or 'FAILED' in line or 'ERROR' in line:
            draw.text((padding, y), line, fill="#f85149", font=font)
        elif '🚀' in line or '📍' in line or '━' in line:
            draw.text((padding, y), line, fill=ACCENT_COLOR, font=font)
        elif line.strip().startswith('//'):
            draw.text((padding, y), line, fill=GRAY_COLOR, font=font)
        elif 'Step' in line and ':' in line:
            draw.text((padding, y), line, fill=YELLOW_COLOR, font=font)
        else:
            draw.text((padding, y), line, fill=TEXT_COLOR, font=font)
        y += LINE_HEIGHT

    # Save
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    img.save(output_path)
    print(f"Created: {output_path}")


def main():
    assets_dir = "assets"

    # Screenshot 1: CLI Overview
    cli_content = """$ nlwa --help

 Usage: nlwa [OPTIONS] COMMAND [ARGS]...

 NLWebAgent - Natural Language Web Testing Agent

+- Options -------------------------------------------------------------------+
| --version  -v        Show version and exit                                  |
| --help               Show this message and exit.                            |
+-----------------------------------------------------------------------------+
+- Commands ------------------------------------------------------------------+
| run      Execute web automation task                                        |
| test     Run natural language tests                                         |
| assert   Run semantic assertions on web pages                               |
| record   Record session and generate Playwright test code                   |
+-----------------------------------------------------------------------------+"""

    create_terminal_screenshot(
        "Terminal - nlwa",
        cli_content,
        f"{assets_dir}/cli-overview.png"
    )

    # Screenshot 2: Test Run Example
    test_content = """$ nlwa test "Verify login shows dashboard" --url https://example.com/login

🚀 Starting test: "Verify login shows dashboard"
📍 URL: https://example.com/login

Step 1/10: Analyzing page...
  └─ Action: TYPE:#email → test@example.com
Step 2/10: Typing password...
  └─ Action: TYPE:#password → ********
Step 3/10: Submitting form...
  └─ Action: CLICK:button[type="submit"]
Step 4/10: Verifying dashboard loaded...
  └─ Action: EXTRACT:h1.dashboard-title → "Welcome Back"
Step 5/10: Test verification...
  └─ Action: DONE

✅ TEST PASSED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Duration: 4.2s | Steps: 5 | Model: llama3.2-vision (local)
Artifacts: 📹 video.webm  📝 transcript.json  📸 5 screenshots"""

    create_terminal_screenshot(
        "Terminal - test run",
        test_content,
        f"{assets_dir}/test-run-example.png",
        width=850
    )

    # Screenshot 3: Generated Playwright Code
    codegen_content = """$ nlwa record --url https://example.com/login --output login.spec.ts

📝 Recording session... Press Ctrl+C to stop.
✅ Session recorded: 5 actions captured
📄 Generated: login.spec.ts

// Generated by NLWebAgent - login.spec.ts
import { test, expect } from '@playwright/test';

test('login shows dashboard', async ({ page }) => {
  await page.goto('https://example.com/login');

  // Fill credentials
  await page.fill('#email', 'test@example.com');
  await page.fill('#password', 'your-password');

  // Submit form
  await page.click('button[type="submit"]');

  // Verify dashboard loaded
  await expect(page.locator('h1.dashboard-title')).toContainText('Welcome Back');

  // Suggestion: Add assertion for user avatar
  // await expect(page.locator('.user-avatar')).toBeVisible();
});"""

    create_terminal_screenshot(
        "Terminal - codegen",
        codegen_content,
        f"{assets_dir}/codegen-example.png",
        width=850
    )

    # Screenshot 4: Assertion Example
    assert_content = """$ nlwa assert "price < 50" --url https://shop.example.com/product/123

🔍 Assertion: price < 50
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Extracted value: "$42.99" → 42.99
Comparison: 42.99 < 50
✅ ASSERTION PASSED

$ nlwa assert "title contains 'Welcome'" --url https://example.com

🔍 Assertion: title contains 'Welcome'
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Extracted value: "Welcome to Example"
Comparison: "Welcome to Example" contains "Welcome"
✅ ASSERTION PASSED"""

    create_terminal_screenshot(
        "Terminal - assertions",
        assert_content,
        f"{assets_dir}/assertion-example.png",
        width=750
    )

    print(f"\n✅ Generated 4 screenshots in {assets_dir}/")


if __name__ == "__main__":
    main()

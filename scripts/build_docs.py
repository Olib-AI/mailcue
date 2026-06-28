#!/usr/bin/env python3
import os
import re
import markdown
from pygments.formatters import HtmlFormatter

# Configuration
WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DIR = os.path.join(WORKSPACE_ROOT, "docs")
GUIDES_DIR = os.path.join(DOCS_DIR, "guides")

GUIDES = [
    {"file": "architecture.md", "title": "Architecture", "desc": "Container layout, request flow, and tech stack."},
    {"file": "configuration.md", "title": "Configuration", "desc": "Environment variables and exposed ports."},
    {"file": "api.md", "title": "API Reference", "desc": "REST endpoints, authentication, and API key scopes."},
    {"file": "production.md", "title": "Production Deployment", "desc": "Hardened mode, DNS records, and TLS certificates."},
    {"file": "tunnel.md", "title": "SMTP Tunnel", "desc": "Bypass port-25 blocks on cloud providers with a secure, authenticated SMTP egress tunnel."},
    {"file": "clients.md", "title": "Email Clients & TLS Trust", "desc": "IMAP/POP3/SMTP setup and trusting the CA."},
    {"file": "ci.md", "title": "Using in CI/CD", "desc": "Pipeline setup and platform examples."},
    {"file": "mcp.md", "title": "MCP Server", "desc": "Give an AI agent its own mailbox over MCP."},
    {"file": "sandbox.md", "title": "Provider Sandbox & HTTP Bin", "desc": "Capture SMS, voice, and chat traffic, and inspect HTTP requests."},
    {"file": "networking.md", "title": "Sharing MailCue", "desc": "Run one container behind a shared Docker network."},
    {"file": "development.md", "title": "Development & Contributing", "desc": "Local setup, linting, tests, and the PR process."}
]

# Generate Pygments syntax highlighting CSS
pygments_css = HtmlFormatter(style="monokai").get_style_defs(".codehilite")

# Base Page Template
PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — MailCue Documentation</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="https://olib-ai.github.io/mailcue/guides/{html_filename}" />

<!-- Open Graph / Facebook -->
<meta property="og:type" content="website">
<meta property="og:url" content="https://olib-ai.github.io/mailcue/guides/{html_filename}">
<meta property="og:title" content="{title} — MailCue Documentation">
<meta property="og:description" content="{desc}">
<meta property="og:image" content="https://raw.githubusercontent.com/Olib-AI/mailcue/main/examples/regular-email.png">

<!-- Twitter -->
<meta property="twitter:card" content="summary_large_image">
<meta property="twitter:url" content="https://olib-ai.github.io/mailcue/guides/{html_filename}">
<meta property="twitter:title" content="{title} — MailCue Documentation">
<meta property="twitter:description" content="{desc}">
<meta property="twitter:image" content="https://raw.githubusercontent.com/Olib-AI/mailcue/main/examples/regular-email.png">

<link rel="icon" type="image/svg+xml" href="../favicon.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:ital,wght@0,300;0,400;0,500&family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root {{
  --green-50: #f0fdf4;
  --green-100: #dcfce7;
  --green-200: #bbf7d0;
  --green-300: #7FBD8A;
  --green-400: #52A97C;
  --green-500: #3A7D5C;
  --green-600: #2B5F43;
  --green-700: #1a3d2a;
  --green-900: #0a1a10;
  --bg: #07090a;
  --bg-elevated: #0d1210;
  --bg-card: #111916;
  --border: #1a2820;
  --border-bright: #253d30;
  --text: #e8efe9;
  --text-dim: #7a9484;
  --text-muted: #4a6454;
  --sans: 'Outfit', system-ui, sans-serif;
  --mono: 'DM Mono', 'Fira Code', monospace;
}}
html {{ scroll-behavior: smooth; }}
body {{
  background: var(--bg);
  color: var(--text);
  font-family: var(--sans);
  font-weight: 400;
  line-height: 1.6;
  overflow-x: hidden;
  -webkit-font-smoothing: antialiased;
}}
a {{ color: var(--green-300); text-decoration: none; transition: color .2s; }}
a:hover {{ color: var(--green-200); }}
::selection {{ background: var(--green-600); color: var(--green-50); }}

/* Noise overlay */
body::before {{
  content: '';
  position: fixed;
  inset: 0;
  background: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E");
  background-size: 256px 256px;
  pointer-events: none;
  z-index: 9999;
}}

/* Sticky Nav */
nav {{
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
  padding: 1rem 0;
  backdrop-filter: blur(20px) saturate(1.2);
  -webkit-backdrop-filter: blur(20px) saturate(1.2);
  background: rgba(7,9,10,.7);
  border-bottom: 1px solid var(--border);
}}
.nav-inner {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 2rem;
}}
.nav-logo {{ display: flex; align-items: center; gap: .75rem; font-weight: 600; font-size: 1.2rem; }}
.nav-logo svg {{ width: 32px; height: 32px; }}
.nav-links {{ display: flex; align-items: center; gap: 2rem; }}
.nav-links .gh-btn {{
  display: inline-flex;
  align-items: center;
  gap: .5rem;
  padding: .5rem 1.1rem;
  border: 1px solid var(--border-bright);
  border-radius: 8px;
  font-size: .85rem;
  color: var(--text);
  transition: all .2s;
}}
.nav-links .gh-btn:hover {{ background: var(--bg-card); border-color: var(--green-500); }}
.nav-links .gh-btn svg {{ width: 18px; height: 18px; }}

/* Documentation Layout */
.doc-wrapper {{
  max-width: 1400px;
  margin: 6rem auto 0;
  padding: 2rem;
  display: flex;
  gap: 3rem;
  min-height: calc(100vh - 6rem);
}}

/* Sidebar */
.sidebar {{
  width: 280px;
  flex-shrink: 0;
  position: sticky;
  top: 6rem;
  height: calc(100vh - 10rem);
  overflow-y: auto;
  padding-right: 1rem;
  border-right: 1px solid var(--border);
}}
.sidebar-title {{
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--green-400);
  font-weight: 600;
  margin-bottom: 1rem;
}}
.sidebar-list {{
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}}
.sidebar-link {{
  display: block;
  padding: 0.6rem 1rem;
  border-radius: 8px;
  font-size: 0.92rem;
  color: var(--text-dim);
  transition: all 0.2s;
}}
.sidebar-link:hover {{
  color: var(--text);
  background: rgba(255, 255, 255, 0.02);
}}
.sidebar-link.active {{
  color: var(--green-200);
  background: var(--bg-card);
  border-left: 3px solid var(--green-500);
  font-weight: 500;
  padding-left: calc(1rem - 3px);
}}

/* Main Content */
.main-content {{
  flex: 1;
  min-width: 0;
  max-width: 860px;
}}
.content-body {{
  font-size: 1rem;
  line-height: 1.7;
  color: var(--text);
}}
.content-body h1 {{
  font-size: 2.5rem;
  font-weight: 600;
  margin-bottom: 1.5rem;
  letter-spacing: -0.02em;
  color: var(--text);
}}
.content-body h2 {{
  font-size: 1.6rem;
  font-weight: 500;
  margin-top: 2.5rem;
  margin-bottom: 1rem;
  padding-bottom: 0.4rem;
  border-bottom: 1px solid var(--border);
  color: var(--text);
}}
.content-body h3 {{
  font-size: 1.2rem;
  font-weight: 600;
  margin-top: 1.8rem;
  margin-bottom: 0.8rem;
  color: var(--text);
}}
.content-body p {{
  margin-bottom: 1.2rem;
  color: var(--text-dim);
}}
.content-body ul, .content-body ol {{
  margin-bottom: 1.2rem;
  padding-left: 1.5rem;
  color: var(--text-dim);
}}
.content-body li {{
  margin-bottom: 0.4rem;
}}
.content-body code {{
  font-family: var(--mono);
  font-size: 0.88em;
  background: var(--bg-elevated);
  padding: 0.2rem 0.4rem;
  border-radius: 4px;
  border: 1px solid var(--border);
  color: var(--green-300);
}}
.content-body pre {{
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 1.2rem;
  overflow-x: auto;
  margin-bottom: 1.5rem;
}}
.content-body pre code {{
  background: none;
  border: none;
  padding: 0;
  color: var(--text);
  font-size: 0.85rem;
  line-height: 1.5;
}}
.content-body blockquote {{
  border-left: 4px solid var(--green-500);
  background: var(--bg-card);
  padding: 1rem 1.5rem;
  margin-bottom: 1.5rem;
  border-radius: 0 8px 8px 0;
}}
.content-body blockquote p {{
  margin-bottom: 0;
  color: var(--text-dim);
}}

/* Table Styles */
.content-body table {{
  width: 100%;
  border-collapse: collapse;
  margin-bottom: 1.5rem;
  font-size: 0.9rem;
}}
.content-body th, .content-body td {{
  padding: 0.75rem 1rem;
  border: 1px solid var(--border);
  text-align: left;
}}
.content-body th {{
  background: var(--bg-card);
  color: var(--text);
  font-weight: 500;
}}
.content-body tr:nth-child(even) td {{
  background: rgba(255, 255, 255, 0.01);
}}

/* Mermaid styles */
.mermaid {{
  background: var(--bg-elevated) !important;
  border: 1px solid var(--border) !important;
  border-radius: 10px;
  padding: 1rem;
  margin-bottom: 1.5rem;
  display: flex;
  justify-content: center;
}}

/* Syntax highlighting CSS integration */
{pygments_css}

/* Footer */
footer {{
  border-top: 1px solid var(--border);
  padding: 3rem 0;
  margin-top: 4rem;
}}
.footer-inner {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 2rem;
}}
.footer-left {{ display: flex; align-items: center; gap: .6rem; font-size: .85rem; color: var(--text-muted); }}
.footer-left svg {{ width: 22px; height: 22px; }}
.footer-links {{ display: flex; gap: 2rem; }}
.footer-links a {{ font-size: .85rem; color: var(--text-muted); transition: color .2s; }}
.footer-links a:hover {{ color: var(--text); }}

/* Responsive */
@media (max-width: 900px) {{
  .doc-wrapper {{
    flex-direction: column;
    gap: 2rem;
  }}
  .sidebar {{
    width: 100%;
    position: static;
    height: auto;
    border-right: none;
    border-bottom: 1px solid var(--border);
    padding-bottom: 1.5rem;
    padding-right: 0;
  }}
  .sidebar-list {{
    flex-direction: row;
    flex-wrap: wrap;
  }}
  .sidebar-link {{
    padding: 0.4rem 0.8rem;
  }}
  .sidebar-link.active {{
    border-left: none;
    border-bottom: 3px solid var(--green-500);
    padding-left: 0.8rem;
    padding-bottom: calc(0.4rem - 3px);
  }}
}}
</style>
<!-- Mermaid Support -->
<script type="module">
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
mermaid.initialize({{ startOnLoad: true, theme: 'dark', securityLevel: 'loose' }});
</script>
</head>
<body>

<!-- Nav -->
<nav>
  <div class="nav-inner">
    <a href="../index.html" class="nav-logo">
      <svg viewBox="0 0 120 100" fill="none" xmlns="http://www.w3.org/2000/svg">
        <defs><clipPath id="nav-env-clip"><rect x="10" y="10" width="100" height="76" rx="10"/></clipPath></defs>
        <rect x="10" y="10" width="100" height="76" rx="10" fill="#3A7D5C"/>
        <g clip-path="url(#nav-env-clip)">
          <path d="M10 86 L10 52 L56 73 Q60 75 64 73 L110 52 L110 86 Z" fill="#52A97C"/>
          <path d="M10 10 L110 10 L110 48 L64 67 Q60 69 56 67 L10 48 Z" fill="#2B5F43"/>
        </g>
        <circle cx="102" cy="16" r="15" fill="#7FBD8A" stroke="white" stroke-width="2.5"/>
        <path d="M94.5 16.5 L99 21 L109.5 11" fill="none" stroke="white" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      MailCue
    </a>
    <div class="nav-links">
      <a href="../index.html" style="font-size:0.9rem; color:var(--text-dim); margin-right:1rem;">Home</a>
      <a href="https://github.com/Olib-AI/mailcue" class="gh-btn">
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/></svg>
        GitHub
      </a>
    </div>
  </div>
</nav>

<div class="doc-wrapper">
  <!-- Sidebar -->
  <aside class="sidebar">
    <div class="sidebar-title">Guides</div>
    <ul class="sidebar-list">
      {sidebar_links}
    </ul>
  </aside>

  <!-- Main Content -->
  <main class="main-content">
    <article class="content-body">
      {content}
    </article>
  </main>
</div>

<!-- Footer -->
<footer>
  <div class="container">
    <div class="footer-inner">
      <div class="footer-left">
        <svg viewBox="0 0 120 100" fill="none" xmlns="http://www.w3.org/2000/svg">
          <defs><clipPath id="footer-env-clip"><rect x="10" y="10" width="100" height="76" rx="10"/></clipPath></defs>
          <rect x="10" y="10" width="100" height="76" rx="10" fill="#3A7D5C"/>
          <g clip-path="url(#footer-env-clip)">
            <path d="M10 86 L10 52 L56 73 Q60 75 64 73 L110 52 L110 86 Z" fill="#52A97C"/>
            <path d="M10 10 L110 10 L110 48 L64 67 Q60 69 56 67 L10 48 Z" fill="#2B5F43"/>
          </g>
          <circle cx="102" cy="16" r="15" fill="#7FBD8A" stroke="white" stroke-width="2.5"/>
          <path d="M94.5 16.5 L99 21 L109.5 11" fill="none" stroke="white" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        Built by <a href="https://www.olib.ai" style="margin-left:.3rem">Olib AI</a>
      </div>
      <div class="footer-links">
        <a href="https://github.com/Olib-AI/mailcue">GitHub</a>
        <a href="https://github.com/Olib-AI/mailcue/issues">Issues</a>
        <a href="https://github.com/Olib-AI/mailcue/discussions">Discussions</a>
        <a href="https://github.com/Olib-AI/mailcue/blob/main/LICENSE">MIT License</a>
      </div>
    </div>
  </div>
</footer>

<!-- Structured Data -->
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    {{
      "@type": "ListItem",
      "position": 1,
      "name": "Home",
      "item": "https://olib-ai.github.io/mailcue/"
    }},
    {{
      "@type": "ListItem",
      "position": 2,
      "name": "{title}",
      "item": "https://olib-ai.github.io/mailcue/guides/{html_filename}"
    }}
  ]
}}
</script>
</body>
</html>
"""

def generate_docs():
    print("Generating HTML documentation...")
    
    # Auto-copy and adapt tunnel README to docs/guides/tunnel.md
    tunnel_readme = os.path.join(WORKSPACE_ROOT, "tunnel", "README.md")
    tunnel_guide = os.path.join(GUIDES_DIR, "tunnel.md")
    if os.path.exists(tunnel_readme):
        with open(tunnel_readme, "r", encoding="utf-8") as f:
            content = f.read()
        # Fix relative links to tunnel/docs/PROTOCOL.md and SECURITY.md
        content = content.replace("](docs/PROTOCOL.md)", "](https://github.com/Olib-AI/mailcue/blob/main/tunnel/docs/PROTOCOL.md)")
        content = content.replace("](docs/SECURITY.md)", "](https://github.com/Olib-AI/mailcue/blob/main/tunnel/docs/SECURITY.md)")
        with open(tunnel_guide, "w", encoding="utf-8") as f:
            f.write(content)
        print("Copied and adapted tunnel/README.md to docs/guides/tunnel.md")
        
    # Render all markdown guides
    for guide in GUIDES:
        md_file_path = os.path.join(GUIDES_DIR, guide["file"])
        html_filename = guide["file"].replace(".md", ".html")
        html_file_path = os.path.join(GUIDES_DIR, html_filename)
        
        if not os.path.exists(md_file_path):
            print(f"Warning: {md_file_path} not found.")
            continue
            
        with open(md_file_path, "r", encoding="utf-8") as f:
            md_content = f.read()
            
        # Pre-process markdown to extract mermaid blocks before markdown parses them (and codehilite ruins them)
        mermaid_blocks = []
        def extract_mermaid(match):
            block_content = match.group(1).strip()
            mermaid_blocks.append(block_content)
            return f"\n\n<!-- MERMAID_PLACEHOLDER_{len(mermaid_blocks)-1} -->\n\n"
            
        md_content_no_mermaid = re.sub(r'```mermaid([\s\S]*?)```', extract_mermaid, md_content)
            
        # Parse markdown to HTML
        # Using extensions:
        # extra: includes tables, footnotes, attribute lists, etc.
        # codehilite: syntax highlighting
        # fenced_code: code blocks
        html_body = markdown.markdown(md_content_no_mermaid, extensions=['extra', 'codehilite', 'fenced_code'])
        
        # Post-process HTML
        # 1. Map relative markdown links to HTML links
        # Match links to other guides (e.g. 'architecture.md' or '../guides/architecture.md')
        # We replace href=".../guides/name.md" or href="name.md" with the HTML equivalent
        def replace_link(match):
            href = match.group(1)
            # If it's a relative guide link, convert it
            if href.endswith(".md"):
                basename = os.path.basename(href)
                # Map guide names if they exist in our list
                for g in GUIDES:
                    if g["file"] == basename:
                        return f'href="{basename.replace(".md", ".html")}"'
            return match.group(0)
            
        html_body = re.sub(r'href="([^"]+)"', replace_link, html_body)
        
        # 2. Put mermaid blocks back as clean <pre class="mermaid"> tags
        for i, block in enumerate(mermaid_blocks):
            placeholder = f"<!-- MERMAID_PLACEHOLDER_{i} -->"
            p_placeholder = f"<p>{placeholder}</p>"
            mermaid_html = f'<pre class="mermaid">{block}</pre>'
            if p_placeholder in html_body:
                html_body = html_body.replace(p_placeholder, mermaid_html)
            else:
                html_body = html_body.replace(placeholder, mermaid_html)
        
        # 3. Generate Sidebar Links dynamically
        sidebar_links = []
        for g in GUIDES:
            g_html = g["file"].replace(".md", ".html")
            active_class = "active" if g["file"] == guide["file"] else ""
            sidebar_links.append(
                f'<li><a href="{g_html}" class="sidebar-link {active_class}">{g["title"]}</a></li>'
            )
        sidebar_links_str = "\n      ".join(sidebar_links)
        
        # Populate Page Template
        page_html = PAGE_TEMPLATE.format(
            title=guide["title"],
            desc=guide["desc"],
            html_filename=html_filename,
            sidebar_links=sidebar_links_str,
            content=html_body,
            pygments_css=pygments_css
        )
        
        with open(html_file_path, "w", encoding="utf-8") as f:
            f.write(page_html)
            
        print(f"Generated: docs/guides/{html_filename}")

    # Generate robots.txt
    robots_path = os.path.join(DOCS_DIR, "robots.txt")
    with open(robots_path, "w", encoding="utf-8") as f:
        f.write("User-agent: *\nAllow: /\n\nSitemap: https://olib-ai.github.io/mailcue/sitemap.xml\n")
    print("Generated: docs/robots.txt")

    # Generate sitemap.xml
    sitemap_path = os.path.join(DOCS_DIR, "sitemap.xml")
    sitemap_urls = [
        "https://olib-ai.github.io/mailcue/",
    ]
    for g in GUIDES:
        sitemap_urls.append(f"https://olib-ai.github.io/mailcue/guides/{g['file'].replace('.md', '.html')}")
        
    sitemap_xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url in sitemap_urls:
        sitemap_xml.append("  <url>")
        sitemap_xml.append(f"    <loc>{url}</loc>")
        sitemap_xml.append("    <changefreq>weekly</changefreq>")
        sitemap_xml.append("    <priority>1.0</priority>" if url.endswith("/mailcue/") else "    <priority>0.8</priority>")
        sitemap_xml.append("  </url>")
    sitemap_xml.append("</urlset>")
    
    with open(sitemap_path, "w", encoding="utf-8") as f:
        f.write("\n".join(sitemap_xml))
    print("Generated: docs/sitemap.xml")

if __name__ == "__main__":
    generate_docs()

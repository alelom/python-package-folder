#!/usr/bin/env python3
"""
Generic script to fix markdown cross-references for GitHub wiki format.

Converts markdown links like [text](FILENAME.md) or [text](FILENAME.md#anchor)
to wiki-style links like [text](Wiki-Page-Name) or [text](Wiki-Page-Name#anchor).

The script automatically:
1. Detects all markdown links in the file
2. Extracts the target filename
3. Converts it to wiki page name format (Title Case with hyphens)
4. Preserves anchors and link text
"""

import re
import sys
from pathlib import Path


def filename_to_wiki_name(filename: str) -> str:
    """
    Convert a markdown filename to a GitHub wiki page name.
    
    Examples:
    - INSTALLATION.md -> Installation
    - VERSION_RESOLUTION.md -> Version-Resolution
    - USAGE.md -> Usage
    - REFERENCE.md -> API-Reference (special case)
    
    Rules:
    - Remove .md extension
    - Convert underscores to hyphens
    - Convert to Title Case
    - Handle special cases
    """
    # Remove .md extension and any path components
    name = Path(filename).stem
    
    # Special case mappings
    special_cases = {
        'REFERENCE': 'API-Reference',
    }
    
    if name in special_cases:
        return special_cases[name]
    
    # Convert underscores to hyphens
    name = name.replace('_', '-')
    
    # Convert to Title Case (capitalize first letter of each word)
    # Split by hyphens, capitalize each part, join
    parts = name.split('-')
    title_parts = [part.capitalize() for part in parts]
    
    return '-'.join(title_parts)


def fix_markdown_links(content: str, doc_mapping: dict[str, str]) -> str:
    """
    Fix all markdown links in content to use wiki page names.
    
    Args:
        content: The markdown content
        doc_mapping: Dictionary mapping source filenames to wiki page names
    
    Returns:
        Content with fixed links
    """
    # Pattern to match markdown links: [text](target.md) or [text](target.md#anchor)
    # Also handles paths like docs/target.md or ./target.md
    link_pattern = re.compile(
        r'\[([^\]]+)\]\(([^)]+\.md)(#[^)]+)?\)',
        re.IGNORECASE
    )
    
    def replace_link(match):
        link_text = match.group(1)
        target = match.group(2)
        anchor = match.group(3) or ''
        
        # Extract just the filename from the path
        filename = Path(target).name
        
        # Get wiki page name from mapping
        wiki_name = doc_mapping.get(filename.upper())
        
        if wiki_name:
            # Return wiki-style link
            return f'[{link_text}]({wiki_name}{anchor})'
        else:
            # If not in mapping, try to convert generically
            wiki_name = filename_to_wiki_name(filename)
            return f'[{link_text}]({wiki_name}{anchor})'
    
    return link_pattern.sub(replace_link, content)


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: fix_wiki_links.py <file1> [file2] ...", file=sys.stderr)
        sys.exit(1)
    
    # Build mapping from all docs files
    # This assumes we're running from the repo root
    docs_dir = Path('docs')
    if not docs_dir.exists():
        # Try from main-repo directory
        docs_dir = Path('main-repo/docs')
    
    doc_mapping = {}
    if docs_dir.exists():
        for md_file in docs_dir.glob('*.md'):
            filename = md_file.name.upper()
            wiki_name = filename_to_wiki_name(md_file.name)
            doc_mapping[filename] = wiki_name
    
    # Process each file
    for file_path in sys.argv[1:]:
        file_path = Path(file_path)
        if not file_path.exists():
            print(f"Warning: File not found: {file_path}", file=sys.stderr)
            continue
        
        # Read content
        content = file_path.read_text(encoding='utf-8')
        
        # Fix links
        fixed_content = fix_markdown_links(content, doc_mapping)
        
        # Write back
        file_path.write_text(fixed_content, encoding='utf-8')
        print(f"Fixed links in: {file_path}")


if __name__ == '__main__':
    main()

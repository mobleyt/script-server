#!/usr/bin/env python3
"""
Reformat oral history transcripts by swapping speaker names and timestamps.

Changes format from:
    Speaker Name (00:00:00):
To:
    00:00:00 Speaker Name:

This is a standalone script that doesn't require external dependencies.
"""

import io
import re
import argparse
import zipfile
from pathlib import Path
from xml.dom import minidom

DOCUMENT_XML = 'word/document.xml'

# Upper bound on the uncompressed size of a .docx, so a small upload that
# expands enormously (a "zip bomb") is rejected before it is read into memory.
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024


def reformat_docx_bytes(data):
    """
    Reformat a .docx held in memory.

    Returns ``(new_docx_bytes, changes)`` where ``changes`` is the number of
    speaker entries reformatted. Raises ``ValueError`` if the data is not a
    usable .docx. Every part other than word/document.xml is copied unchanged,
    in its original order.
    """
    try:
        src = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("not a valid .docx file")

    with src:
        entries = src.infolist()
        if sum(item.file_size for item in entries) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("document is too large once uncompressed")
        if DOCUMENT_XML not in src.namelist():
            raise ValueError("document.xml not found in document")

        dom = minidom.parseString(src.read(DOCUMENT_XML))
        changes = reformat_dom(dom)

        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as dst:
            for item in entries:
                if item.filename == DOCUMENT_XML:
                    dst.writestr(item, dom.toxml().encode('utf-8'))
                else:
                    dst.writestr(item, src.read(item))

    return out.getvalue(), changes


def find_and_reformat_speakers(xml_file):
    """
    Find and reformat speaker/timestamp patterns in an unpacked document.xml
    file, in place. Returns the count of reformatted entries.
    """
    with open(xml_file, 'r', encoding='utf-8') as f:
        dom = minidom.parseString(f.read())

    changes_made = reformat_dom(dom)

    with open(xml_file, 'w', encoding='utf-8') as f:
        f.write(dom.toxml())

    return changes_made


def reformat_dom(dom):
    """
    Find and reformat speaker/timestamp patterns in a parsed document.xml.
    Returns the count of reformatted entries.
    """
    # Track changes
    changes_made = 0
    last_speaker = None  # Track the last speaker name for continuation timestamps
    paragraphs = dom.getElementsByTagName('w:p')
    
    for para in paragraphs:
        # Get all text runs in this paragraph
        runs = para.getElementsByTagName('w:r')
        hyperlinks = para.getElementsByTagName('w:hyperlink')
        
        if not runs or not hyperlinks:
            continue
        
        # Extract text content to detect pattern
        para_text = ''
        for run in runs:
            t_elems = run.getElementsByTagName('w:t')
            for t_elem in t_elems:
                if t_elem.firstChild:
                    para_text += t_elem.firstChild.nodeValue
        
        # Check for hyperlink timestamps
        timestamp = None
        hyperlink_elem = None
        for hyperlink in hyperlinks:
            t_elems = hyperlink.getElementsByTagName('w:t')
            for t_elem in t_elems:
                if t_elem.firstChild:
                    text = t_elem.firstChild.nodeValue
                    # Match HH:MM:SS or MM:SS pattern
                    if re.match(r'^\d{1,2}:\d{2}(:\d{2})?$', text):
                        timestamp = text
                        hyperlink_elem = hyperlink
                        break
            if timestamp:
                break
        
        if not timestamp or not hyperlink_elem:
            continue
        
        # Check if this is a continuation timestamp (just timestamp with parentheses and colon, no name)
        # Pattern: "(timestamp):" with no text before the opening paren
        if re.match(r'^\s*\([^)]+\)\s*:?\s*$', para_text.strip()):
            # This is a continuation timestamp
            if last_speaker:
                # Use the last speaker's name
                if reformat_paragraph(para, last_speaker, timestamp, hyperlink_elem):
                    changes_made += 1
            continue
        
        # Look for pattern: "Name (timestamp):"
        # Simplified check: if we have timestamp and parentheses, likely a speaker line
        if '(' in para_text and ')' in para_text and ':' in para_text:
            # Extract speaker name (everything before the opening paren)
            match = re.match(r'^([^(]+)\s*\([^)]+\)\s*:?\s*$', para_text.strip())
            if match:
                speaker_name = match.group(1).strip()
                last_speaker = speaker_name  # Remember this speaker for continuations
                
                # Now rebuild this paragraph with new structure
                if reformat_paragraph(para, speaker_name, timestamp, hyperlink_elem):
                    changes_made += 1

    return changes_made


def reformat_paragraph(para, speaker_name, timestamp, hyperlink_elem):
    """
    Reformat a paragraph to swap speaker and timestamp.
    Returns True if successful.
    """
    try:
        # Get the hyperlink's relationship ID
        rel_id = hyperlink_elem.getAttribute('r:id')
        if not rel_id:
            # Try other possible attributes
            rel_id = hyperlink_elem.getAttribute('w:anchor')
        if not rel_id:
            # Look for it in child elements
            for attr_name in hyperlink_elem.attributes.keys():
                if 'id' in attr_name.lower():
                    rel_id = hyperlink_elem.getAttribute(attr_name)
                    break
        
        if not rel_id:
            return False
        
        # Convert speaker name to uppercase
        speaker_name = speaker_name.upper()
        
        # Clear all child elements from paragraph except pPr
        children = list(para.childNodes)
        p_pr = None
        for child in children:
            if child.nodeType == child.ELEMENT_NODE and child.tagName == 'w:pPr':
                p_pr = child
            else:
                para.removeChild(child)
        
        # Build new content: timestamp (hyperlink), space, speaker name (no colon)
        
        # 1. Hyperlink with timestamp
        new_hyperlink = para.ownerDocument.createElement('w:hyperlink')
        new_hyperlink.setAttribute('r:id', rel_id)
        
        hyper_run = para.ownerDocument.createElement('w:r')
        hyper_rpr = para.ownerDocument.createElement('w:rPr')
        
        # Add formatting
        add_font_prop(hyper_rpr, para.ownerDocument)
        add_element(hyper_rpr, para.ownerDocument, 'w:b', {'w:val': '0'})
        add_element(hyper_rpr, para.ownerDocument, 'w:i', {'w:val': '0'})
        add_element(hyper_rpr, para.ownerDocument, 'w:color', {'w:val': '0000FF'})
        add_element(hyper_rpr, para.ownerDocument, 'w:sz', {'w:val': '22'})
        add_element(hyper_rpr, para.ownerDocument, 'w:u', {'w:val': 'single'})
        
        hyper_run.appendChild(hyper_rpr)
        
        hyper_t = para.ownerDocument.createElement('w:t')
        hyper_t.appendChild(para.ownerDocument.createTextNode(timestamp))
        hyper_run.appendChild(hyper_t)
        new_hyperlink.appendChild(hyper_run)
        
        # 2. Space run
        space_run = para.ownerDocument.createElement('w:r')
        space_rpr = para.ownerDocument.createElement('w:rPr')
        add_font_prop(space_rpr, para.ownerDocument)
        add_element(space_rpr, para.ownerDocument, 'w:b', {'w:val': '0'})
        add_element(space_rpr, para.ownerDocument, 'w:i', {'w:val': '0'})
        add_element(space_rpr, para.ownerDocument, 'w:color', {'w:val': '000000'})
        add_element(space_rpr, para.ownerDocument, 'w:sz', {'w:val': '22'})
        add_element(space_rpr, para.ownerDocument, 'w:u', {'w:val': 'none'})
        space_run.appendChild(space_rpr)
        
        space_t = para.ownerDocument.createElement('w:t')
        space_t.setAttribute('xml:space', 'preserve')
        space_t.appendChild(para.ownerDocument.createTextNode(' '))
        space_run.appendChild(space_t)
        
        # 3. Speaker name run (uppercase, no colon)
        name_run = para.ownerDocument.createElement('w:r')
        name_rpr = para.ownerDocument.createElement('w:rPr')
        add_font_prop(name_rpr, para.ownerDocument)
        add_element(name_rpr, para.ownerDocument, 'w:b', {'w:val': '0'})
        add_element(name_rpr, para.ownerDocument, 'w:i', {'w:val': '0'})
        add_element(name_rpr, para.ownerDocument, 'w:color', {'w:val': '000000'})
        add_element(name_rpr, para.ownerDocument, 'w:sz', {'w:val': '22'})
        add_element(name_rpr, para.ownerDocument, 'w:u', {'w:val': 'none'})
        name_run.appendChild(name_rpr)
        
        name_t = para.ownerDocument.createElement('w:t')
        name_t.appendChild(para.ownerDocument.createTextNode(speaker_name))
        name_run.appendChild(name_t)
        
        # Add all elements to paragraph (no colon run)
        if p_pr:
            para.appendChild(p_pr)
        para.appendChild(new_hyperlink)
        para.appendChild(space_run)
        para.appendChild(name_run)
        
        return True
        
    except Exception as e:
        print(f"    Error reformatting paragraph: {e}")
        return False


def add_font_prop(rpr, doc):
    """Add font properties to run properties"""
    fonts = doc.createElement('w:rFonts')
    fonts.setAttribute('w:ascii', 'Calibri')
    fonts.setAttribute('w:hAnsi', 'Calibri')
    fonts.setAttribute('w:eastAsia', 'Calibri')
    fonts.setAttribute('w:cs', 'Calibri')
    rpr.appendChild(fonts)


def add_element(parent, doc, tag, attrs):
    """Add an element with attributes"""
    elem = doc.createElement(tag)
    for key, val in attrs.items():
        elem.setAttribute(key, val)
    parent.appendChild(elem)


def process_transcript(input_path, output_path):
    """Process a single transcript file."""
    print(f"\nProcessing: {input_path}")

    try:
        print("  Finding and reformatting speaker/timestamp patterns...")
        new_docx, changes = reformat_docx_bytes(Path(input_path).read_bytes())
        print(f"  Successfully reformatted {changes} speaker entries")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(new_docx)

        print(f"  Saved to: {output_path}")
        return True

    except ValueError as e:
        print(f"  Error: {e}")
        return False

    except Exception as e:
        print(f"  Error processing document: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Reformat oral history transcripts by swapping speaker names and timestamps',
        epilog="""
Examples:
  Single file:
    python reformat_transcripts.py input.docx output.docx
  
  Multiple files:
    python reformat_transcripts.py input_dir/ output_dir/
        """
    )
    parser.add_argument('input', help='Input .docx file or directory of .docx files')
    parser.add_argument('output', help='Output .docx file or directory')
    
    args = parser.parse_args()
    
    input_path = Path(args.input)
    output_path = Path(args.output)
    
    # Handle single file
    if input_path.is_file():
        if not input_path.suffix.lower() == '.docx':
            print("Error: Input file must be a .docx file")
            return 1
        
        # If output is a directory, use input filename
        if output_path.is_dir():
            output_file = output_path / input_path.name
        else:
            output_file = output_path
        
        output_file.parent.mkdir(parents=True, exist_ok=True)
        success = process_transcript(input_path, output_file)
        return 0 if success else 1
    
    # Handle directory of files
    elif input_path.is_dir():
        output_path.mkdir(parents=True, exist_ok=True)
        
        docx_files = list(input_path.glob("*.docx"))
        if not docx_files:
            print(f"No .docx files found in {input_path}")
            return 1
        
        print(f"Found {len(docx_files)} .docx files to process")
        
        success_count = 0
        for docx_file in docx_files:
            output_file = output_path / docx_file.name
            if process_transcript(docx_file, output_file):
                success_count += 1
        
        print(f"\n{'='*60}")
        print(f"Successfully processed {success_count}/{len(docx_files)} files")
        return 0 if success_count == len(docx_files) else 1
    
    else:
        print(f"Error: {input_path} does not exist")
        return 1


if __name__ == '__main__':
    import sys
    sys.exit(main())

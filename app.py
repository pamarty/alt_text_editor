import os
import tempfile
from flask import Flask, request, render_template, send_file, jsonify
from werkzeug.utils import secure_filename
import zipfile
import re
from urllib.parse import urljoin
import base64
import logging
import chardet
from lxml import etree

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max-limit

APP_TITLE = "desLibris Alt-text Editor"

logging.basicConfig(level=logging.DEBUG)

def generate_valid_id(src):
    base_id = re.sub(r'[^\w\-]', '', src.replace(' ', '-'))
    return f"desc-{base_id}"

def extract_images_and_descriptions(epub_path):
    images = []
    with zipfile.ZipFile(epub_path, 'r') as zip_ref:
        opf_path = next((f for f in zip_ref.namelist() if f.endswith('.opf')), None)
        if not opf_path:
            return images

        with zip_ref.open(opf_path) as opf_file:
            opf_content = opf_file.read()
            encoding = chardet.detect(opf_content)['encoding'] or 'utf-8'
            opf_content = opf_content.decode(encoding)
            parser = etree.XMLParser(recover=True, encoding=encoding)
            opf_tree = etree.fromstring(opf_content.encode(encoding), parser=parser)
            
            ns = {'opf': 'http://www.idpf.org/2007/opf'}
            content_files = opf_tree.xpath('//opf:item[@media-type="application/xhtml+xml"]/@href', namespaces=ns)
            content_files = [urljoin(opf_path, f) for f in content_files]

        for file_name in content_files:
            with zip_ref.open(file_name) as file:
                content = file.read()
                encoding = chardet.detect(content)['encoding'] or 'utf-8'
                content = content.decode(encoding)
                img_tags = re.findall(r'<img[^>]+>', content)
                for img_tag in img_tags:
                    src = re.search(r'src="([^"]+)"', img_tag)
                    alt = re.search(r'alt="([^"]*)"', img_tag)
                    aria_details = re.search(r'aria-details="([^"]+)"', img_tag)
                    
                    if src:
                        src = src.group(1)
                        alt = alt.group(1) if alt else ''
                        long_desc = ''
                        
                        if aria_details:
                            details_id = aria_details.group(1)
                            details_match = re.search(rf'<details[^>]*id="{details_id}"[^>]*>(.*?)</details>', content, re.DOTALL)
                            if details_match:
                                long_desc = re.sub(r'<summary>.*?</summary>', '', details_match.group(1), flags=re.DOTALL).strip()
                        
                        image_path = urljoin(file_name, src)
                        if image_path in zip_ref.namelist():
                            with zip_ref.open(image_path) as img_file:
                                img_data = img_file.read()
                                img_base64 = base64.b64encode(img_data).decode('utf-8')
                                images.append({
                                    'src': image_path,
                                    'alt': alt,
                                    'long_desc': long_desc,
                                    'thumbnail': f"data:image/jpeg;base64,{img_base64}"
                                })
    return images

def update_epub_descriptions(epub_path, new_descriptions):
    temp_dir = tempfile.mkdtemp()
    new_epub_path = os.path.join(temp_dir, 'updated_' + os.path.basename(epub_path))
    
    with zipfile.ZipFile(epub_path, 'r') as zip_ref:
        with zipfile.ZipFile(new_epub_path, 'w', zipfile.ZIP_DEFLATED) as new_zip:
            # Ensure mimetype is the first file
            if 'mimetype' in zip_ref.namelist():
                new_zip.writestr('mimetype', zip_ref.read('mimetype'), compress_type=zipfile.ZIP_STORED)

            # Process OPF file
            opf_path = next((f for f in zip_ref.namelist() if f.endswith('.opf')), None)
            if opf_path:
                with zip_ref.open(opf_path) as opf_file:
                    opf_content = opf_file.read()
                    encoding = 'utf-8'  # Force UTF-8 encoding
                    opf_content = opf_content.decode(encoding, errors='ignore')
                    parser = etree.XMLParser(recover=True, encoding=encoding)
                    opf_tree = etree.fromstring(opf_content.encode(encoding), parser=parser)
                    
                    ns = {'opf': 'http://www.idpf.org/2007/opf'}
                    
                    # Ensure cover image is correctly specified
                    metadata = opf_tree.find('.//opf:metadata', namespaces=ns)
                    cover_meta = metadata.find('meta[@name="cover"]')
                    if cover_meta is None:
                        cover_meta = etree.SubElement(metadata, 'meta', name="cover", content="cover-image")
                    
                    manifest = opf_tree.find('.//opf:manifest', namespaces=ns)
                    cover_item = manifest.find('opf:item[@id="cover-image"]', namespaces=ns)
                    if cover_item is None:
                        cover_item = etree.SubElement(manifest, 'item', id="cover-image", href="images/cover.jpg", media_type="image/jpeg")
                    
                    # Ensure correct MIME types for content files
                    for item in manifest.findall('opf:item', namespaces=ns):
                        href = item.get('href')
                        if href.endswith('.xhtml'):
                            item.set('media-type', 'application/xhtml+xml')
                        elif href.endswith('.html') or href.endswith('.htm'):
                            item.set('media-type', 'text/html')
                        elif href.endswith('.ncx'):
                            item.set('media-type', 'application/x-dtbncx+xml')
                    
                    spine = opf_tree.find('.//opf:spine', namespaces=ns)
                    cover_itemref = spine.find('opf:itemref[@idref="cover"]', namespaces=ns)
                    if cover_itemref is None:
                        cover_itemref = etree.Element('itemref', idref="cover")
                        spine.insert(0, cover_itemref)
                    
                    new_opf_content = etree.tostring(opf_tree, encoding=encoding, xml_declaration=True).decode(encoding)
                    new_zip.writestr(opf_path, new_opf_content.encode(encoding))
            
            # Process content files
            for item in zip_ref.infolist():
                if item.filename == opf_path or item.filename == 'mimetype':
                    continue  # Already processed
                if item.filename.endswith(('.xhtml', '.html', '.htm')):
                    with zip_ref.open(item.filename) as file:
                        content = file.read()
                        encoding = 'utf-8'  # Force UTF-8 encoding
                        content_str = content.decode(encoding, errors='ignore')
                        
                        # Keep track of used IDs to prevent duplicates
                        used_ids = set()
                        
                        def generate_unique_id(base_id):
                            unique_id = base_id
                            counter = 1
                            while unique_id in used_ids:
                                unique_id = f"{base_id}-{counter}"
                                counter += 1
                            used_ids.add(unique_id)
                            return unique_id

                        # Update img tags and add/update details tags
                        def update_content(match):
                            full_match = match.group(1)
                            img_match = re.search(r'<img[^>]+>', full_match)
                            if img_match:
                                img_tag = img_match.group(0)
                                src = re.search(r'src="([^"]+)"', img_tag)
                                if src:
                                    src = urljoin(item.filename, src.group(1))
                                    if src in new_descriptions:
                                        # Update alt text
                                        img_tag = re.sub(r'alt="[^"]*"', f'alt="{new_descriptions[src]["alt"]}"', img_tag)
                                        
                                        # Extract the existing aria-details value if it exists
                                        aria_details_match = re.search(r'aria-details="([^"]*)"', img_tag)
                                        existing_aria_details = aria_details_match.group(1) if aria_details_match else None
                                        
                                        # Create a shorter ID for the details tag
                                        short_id = re.search(r'([^/]+)\.[^.]+$', src)
                                        short_id = short_id.group(1) if short_id else 'img'
                                        short_details_id = f"longdesc-{short_id}"
                                        
                                        if 'long_desc' in new_descriptions[src] and new_descriptions[src]['long_desc'].strip():
                                            # Add aria-details only if it doesn't exist
                                            if not existing_aria_details:
                                                img_tag = img_tag.rstrip('>').rstrip('/') + f' aria-details="{short_details_id}"/>'
                                            
                                            # Create or update details tag (using the new shorter ID)
                                            details_tag = f'\n<details id="{short_details_id}"><summary>Description</summary><p>{new_descriptions[src]["long_desc"]}</p></details>'
                                            
                                            # Check if we're inside a <figure> tag
                                            if full_match.startswith('<figure'):
                                                # Insert details tag after the figure
                                                full_match = full_match.rstrip() + details_tag
                                            else:
                                                # For inline images, wrap both img and details in a div
                                                full_match = f'<div>{img_tag}{details_tag}</div>'
                                        else:
                                            # Remove aria-details if there's no long description
                                            img_tag = re.sub(r'\s*aria-details="[^"]*"', '', img_tag)
                                        
                                        # Ensure img tag is properly formatted
                                        if not img_tag.endswith('/>'):
                                            img_tag = img_tag.rstrip('>').rstrip('/') + '/>'
                                        
                                        if full_match.startswith('<figure'):
                                            full_match = re.sub(r'<img[^>]+>', img_tag, full_match)
                                        else:
                                            full_match = img_tag
                            
                            return full_match

                        # Update content for all img tags
                        content_str = re.sub(r'(<img[^>]+>)', update_content, content_str)

                        # Update content within figure tags containing images
                        content_str = re.sub(r'(<figure[^>]*>.*?</figure>)', update_content, content_str, flags=re.DOTALL)

                        new_zip.writestr(item.filename, content_str.encode(encoding))
                elif item.filename.endswith('nav.xhtml'):
                    # Process navigation file to remove fragment identifiers
                    with zip_ref.open(item.filename) as file:
                        content = file.read().decode('utf-8')
                        # Remove all fragment identifiers from href attributes
                        content = re.sub(r'href="([^"]+)#[^"]*"', r'href="\1"', content)
                        new_zip.writestr(item.filename, content.encode('utf-8'))
                else:
                    new_zip.writestr(item.filename, zip_ref.read(item.filename))
    
    return new_epub_path

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
        if file and file.filename.endswith('.epub'):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            images = extract_images_and_descriptions(file_path)
            return render_template('edit.html', images=images, filename=filename, app_title=APP_TITLE)
    return render_template('upload.html', app_title=APP_TITLE)

@app.route('/update', methods=['POST'])
def update_descriptions():
    try:
        filename = request.form['filename']
        new_descriptions = {}
        for key, value in request.form.items():
            if key.startswith('alt_'):
                src = key[4:]
                if src not in new_descriptions:
                    new_descriptions[src] = {}
                new_descriptions[src]['alt'] = value
            elif key.startswith('long_desc_'):
                src = key[10:]
                if src not in new_descriptions:
                    new_descriptions[src] = {}
                new_descriptions[src]['long_desc'] = value
        
        # Remove entries where neither alt text nor long description has changed
        new_descriptions = {k: v for k, v in new_descriptions.items() if v.get('alt') or v.get('long_desc')}
        
        epub_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        updated_epub_path = update_epub_descriptions(epub_path, new_descriptions)
        return send_file(updated_epub_path, as_attachment=True, download_name=f"updated_{filename}")
    except Exception as e:
        app.logger.error(f"Error updating EPUB: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
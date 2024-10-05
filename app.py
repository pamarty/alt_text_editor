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
from bs4 import BeautifulSoup

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
            content_files = re.findall(r'href="([^"]+\.x?html?)"', opf_content)
            content_files = [urljoin(opf_path, f) for f in content_files]

        for file_name in content_files:
            with zip_ref.open(file_name) as file:
                content = file.read()
                encoding = chardet.detect(content)['encoding'] or 'utf-8'
                content = content.decode(encoding)
                soup = BeautifulSoup(content, 'html.parser')
                for img in soup.find_all('img'):
                    src = img.get('src')
                    if src:
                        alt = img.get('alt', '')
                        long_desc = ''
                        
                        aria_details = img.get('aria-details')
                        if aria_details:
                            details = soup.find('details', id=aria_details)
                            if details:
                                summary = details.find('summary')
                                if summary:
                                    summary.extract()
                                long_desc = details.get_text(strip=True)
                        
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
        with zipfile.ZipFile(new_epub_path, 'w') as new_zip:
            for item in zip_ref.infolist():
                with zip_ref.open(item.filename) as file:
                    content = file.read()
                    if item.filename.endswith(('.xhtml', '.html', '.htm')):
                        encoding = chardet.detect(content)['encoding'] or 'utf-8'
                        content_str = content.decode(encoding)
                        
                        # Use BeautifulSoup for parsing
                        soup = BeautifulSoup(content_str, 'html.parser')
                        
                        for img in soup.find_all('img'):
                            src = urljoin(item.filename, img.get('src', ''))
                            if src in new_descriptions:
                                img['alt'] = new_descriptions[src]['alt']
                                details_id = generate_valid_id(src)
                                img['aria-details'] = details_id
                                
                                if 'long_desc' in new_descriptions[src]:
                                    new_long_desc = new_descriptions[src]['long_desc']
                                    existing_details = soup.find('details', id=details_id)
                                    
                                    if new_long_desc:
                                        if not existing_details:
                                            details_tag = soup.new_tag('details', id=details_id)
                                            summary_tag = soup.new_tag('summary')
                                            summary_tag.string = 'Description'
                                            details_tag.append(summary_tag)
                                            p_tag = soup.new_tag('p')
                                            p_tag.string = new_long_desc
                                            details_tag.append(p_tag)
                                            img.insert_after(details_tag)
                                        else:
                                            p_tag = existing_details.find('p') or soup.new_tag('p')
                                            p_tag.string = new_long_desc
                                            if p_tag.parent != existing_details:
                                                existing_details.append(p_tag)
                                    elif existing_details:
                                        existing_details.decompose()
                        
                        # Convert soup back to string while preserving original formatting
                        new_content = str(soup)
                        
                        # Ensure self-closing tags
                        new_content = re.sub(r'<(area|base|br|col|embed|hr|img|input|link|meta|param|source|track|wbr)([^>]*)></\1>', r'<\1\2 />', new_content)
                        
                        content = new_content.encode(encoding)
                    
                    new_zip.writestr(item.filename, content)
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
        epub_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        updated_epub_path = update_epub_descriptions(epub_path, new_descriptions)
        return send_file(updated_epub_path, as_attachment=True, download_name=f"updated_{filename}")
    except Exception as e:
        app.logger.error(f"Error updating EPUB: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
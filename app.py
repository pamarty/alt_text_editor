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
            encoding = chardet.detect(opf_content)['encoding']
            opf_content = opf_content.decode(encoding)
            content_files = re.findall(r'href="([^"]+\.x?html?)"', opf_content)
            content_files = [urljoin(opf_path, f) for f in content_files]

        for file_name in content_files:
            with zip_ref.open(file_name) as file:
                content = file.read()
                encoding = chardet.detect(content)['encoding']
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
        with zipfile.ZipFile(new_epub_path, 'w') as new_zip:
            for item in zip_ref.infolist():
                with zip_ref.open(item.filename) as file:
                    content = file.read()
                    if item.filename.endswith(('.xhtml', '.html', '.htm')):
                        encoding = chardet.detect(content)['encoding']
                        content = content.decode(encoding)
                        
                        # Update img tags
                        def update_img(match):
                            img_tag = match.group(0)
                            src = re.search(r'src="([^"]+)"', img_tag)
                            if src:
                                src = urljoin(item.filename, src.group(1))
                                if src in new_descriptions:
                                    img_tag = re.sub(r'alt="[^"]*"', f'alt="{new_descriptions[src]["alt"]}"', img_tag)
                                    details_id = generate_valid_id(src)
                                    img_tag = re.sub(r'aria-details="[^"]*"', f'aria-details="{details_id}"', img_tag)
                                    if 'aria-details' not in img_tag:
                                        img_tag = img_tag[:-1] + f' aria-details="{details_id}">'
                            return img_tag

                        content = re.sub(r'<img[^>]+>', update_img, content)
                        
                        # Update or add details tags
                        for src, desc in new_descriptions.items():
                            if 'long_desc' in desc:
                                details_id = generate_valid_id(src)
                                details_tag = f'<details id="{details_id}"><summary>Description</summary><p>{desc["long_desc"]}</p></details>'
                                existing_details = re.search(rf'<details[^>]*id="{details_id}".*?</details>', content, re.DOTALL)
                                if existing_details:
                                    content = content.replace(existing_details.group(0), details_tag)
                                else:
                                    img_tag = re.search(rf'<img[^>]*src="[^"]*{re.escape(os.path.basename(src))}"[^>]*>', content)
                                    if img_tag:
                                        content = content.replace(img_tag.group(0), img_tag.group(0) + details_tag)
                        
                        content = content.encode(encoding)
                    
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
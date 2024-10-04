import os
import tempfile
from flask import Flask, request, render_template, send_file, jsonify
from werkzeug.utils import secure_filename
import zipfile
import re
from urllib.parse import urljoin
import base64

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max-limit

APP_TITLE = "desLibris Alt-text Editor"

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
            opf_content = opf_file.read().decode('utf-8')
            content_files = re.findall(r'href="([^"]+\.x?html?)"', opf_content)
            content_files = [urljoin(opf_path, f) for f in content_files]

        for file_name in content_files:
            with zip_ref.open(file_name) as file:
                content = file.read().decode('utf-8')
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
                    if item.filename.endswith(('.xhtml', '.html', '.htm')):
                        content = file.read().decode('utf-8')
                        
                        def replace_img(match):
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

                        content = re.sub(r'<img[^>]+>', replace_img, content)
                        
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
                        
                        new_zip.writestr(item.filename, content.encode('utf-8'))
                    else:
                        new_zip.writestr(item.filename, file.read())
    return new_epub_path

# ... [The rest of the Flask routes remain the same] ...

if __name__ == '__main__':
    app.run(debug=True)
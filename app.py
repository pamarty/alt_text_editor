import os
import tempfile
from flask import Flask, request, render_template, send_file, jsonify
from werkzeug.utils import secure_filename
import zipfile
from bs4 import BeautifulSoup
import base64
from urllib.parse import urljoin
import re

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max-limit

APP_TITLE = "desLibris Alt-text Editor"

def extract_images_and_descriptions(epub_path):
    images = []
    with zipfile.ZipFile(epub_path, 'r') as zip_ref:
        opf_path = next((f for f in zip_ref.namelist() if f.endswith('.opf')), None)
        if not opf_path:
            return images

        with zip_ref.open(opf_path) as opf_file:
            opf_soup = BeautifulSoup(opf_file, 'html5lib')
            manifest = opf_soup.find('manifest')
            if not manifest:
                return images

            content_files = [urljoin(opf_path, item['href']) for item in manifest.find_all('item', attrs={'media-type': 'application/xhtml+xml'})]

        for file_name in content_files:
            with zip_ref.open(file_name) as file:
                soup = BeautifulSoup(file, 'html5lib')
                for figure in soup.find_all('figure'):
                    img = figure.find('img')
                    if img:
                        src = img.get('src')
                        alt = img.get('alt', '')
                        long_desc = ''
                        
                        # Find long description in the associated details tag
                        details_id = img.get('aria-details')
                        if details_id:
                            details_tag = soup.find('details', id=details_id)
                            if details_tag:
                                # Extract content without the summary
                                summary = details_tag.find('summary')
                                if summary:
                                    summary.extract()
                                long_desc = details_tag.get_text(strip=True)
                        
                        if src:
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
                        
                        # Extract XML declaration and DOCTYPE
                        xml_decl_match = re.match(r'(<\?xml[^>]+\?>)', content)
                        doctype_match = re.search(r'(<!DOCTYPE[^>]+>)', content)
                        xml_decl = xml_decl_match.group(1) if xml_decl_match else ''
                        doctype = doctype_match.group(1) if doctype_match else ''
                        
                        soup = BeautifulSoup(content, 'html5lib')
                        for figure in soup.find_all('figure'):
                            img = figure.find('img')
                            if img:
                                src = urljoin(item.filename, img.get('src'))
                                if src in new_descriptions:
                                    img['alt'] = new_descriptions[src]['alt']
                                    
                                    # Handle long description
                                    details_id = f"desc-{hash(src)}"
                                    existing_details = soup.find('details', id=img.get('aria-details'))
                                    
                                    # Check if the long description was edited
                                    if 'long_desc' in new_descriptions[src]:
                                        new_long_desc = new_descriptions[src]['long_desc']
                                        
                                        if new_long_desc:
                                            # Create or update the details tag
                                            if not existing_details:
                                                details_tag = soup.new_tag('details', id=details_id)
                                                summary_tag = soup.new_tag('summary')
                                                summary_tag.string = 'Description'
                                                details_tag.append(summary_tag)
                                                p_tag = soup.new_tag('p')
                                                details_tag.append(p_tag)
                                            else:
                                                details_tag = existing_details
                                                p_tag = details_tag.find('p') or soup.new_tag('p')
                                                details_tag.clear()
                                                details_tag.append(soup.new_tag('summary', string='Description'))
                                                details_tag.append(p_tag)
                                            
                                            p_tag.string = new_long_desc
                                            img['aria-details'] = details_id
                                            
                                            # Ensure the details tag is after the figure
                                            if existing_details:
                                                existing_details.extract()
                                            figure.insert_after(details_tag)
                                        elif existing_details:
                                            # Remove existing details tag if the new long description is empty
                                            existing_details.decompose()
                                            img.pop('aria-details', None)
                                    # If long_desc is not in new_descriptions[src], it wasn't edited, so do nothing
                        
                        # Reconstruct the content with original XML declaration and DOCTYPE
                        new_content = f"{xml_decl}\n{doctype}\n{soup.prettify()}"
                        new_zip.writestr(item.filename, new_content)
                    else:
                        new_zip.writestr(item.filename, file.read())
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

if __name__ == '__main__':
    app.run(debug=True)
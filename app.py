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
    # ... (keep this function as is) ...

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
                        
                        # Parse the content
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
                        
                        # Reconstruct the content with original XML declaration and DOCTYPE
                        new_content = f"{xml_decl}\n{doctype}\n{soup.prettify()}"
                        new_zip.writestr(item.filename, new_content)
                    else:
                        new_zip.writestr(item.filename, file.read())
    return new_epub_path

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    # ... (keep this function as is) ...

@app.route('/update', methods=['POST'])
def update_descriptions():
    # ... (keep this function as is) ...

if __name__ == '__main__':
    app.run(debug=True)
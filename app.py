import os
import tempfile
from flask import Flask, request, render_template, send_file
from werkzeug.utils import secure_filename
import zipfile
from bs4 import BeautifulSoup
import base64

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = tempfile.gettempdir()  # Use the system's temporary directory
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max-limit

def extract_images_and_descriptions(epub_path):
    images = []
    with zipfile.ZipFile(epub_path, 'r') as zip_ref:
        for file_name in zip_ref.namelist():
            if file_name.endswith(('.xhtml', '.html', '.htm')):
                with zip_ref.open(file_name) as file:
                    soup = BeautifulSoup(file, 'html.parser')
                    for img in soup.find_all('img'):
                        src = img.get('src')
                        alt = img.get('alt', '')
                        # Find long description in parent figure element
                        long_desc = ''
                        figure = img.find_parent('figure')
                        if figure:
                            figcaption = figure.find('figcaption')
                            if figcaption:
                                long_desc = figcaption.get_text(strip=True)
                        if src:
                            image_path = os.path.join(os.path.dirname(file_name), src)
                            if image_path in zip_ref.namelist():
                                with zip_ref.open(image_path) as img_file:
                                    img_data = img_file.read()
                                    img_base64 = base64.b64encode(img_data).decode('utf-8')
                                    images.append({
                                        'src': src,
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
                        soup = BeautifulSoup(content, 'html.parser')
                        for img in soup.find_all('img'):
                            src = img.get('src')
                            if src in new_descriptions:
                                img['alt'] = new_descriptions[src]['alt']
                                figure = img.find_parent('figure')
                                if figure:
                                    figcaption = figure.find('figcaption')
                                    if figcaption:
                                        figcaption.string = new_descriptions[src]['long_desc']
                                    else:
                                        figure.append(soup.new_tag('figcaption'))
                                        figure.figcaption.string = new_descriptions[src]['long_desc']
                                else:
                                    new_figure = soup.new_tag('figure')
                                    img.wrap(new_figure)
                                    new_figcaption = soup.new_tag('figcaption')
                                    new_figcaption.string = new_descriptions[src]['long_desc']
                                    new_figure.append(new_figcaption)
                        new_zip.writestr(item.filename, str(soup))
                    else:
                        new_zip.writestr(item.filename, file.read())
    return new_epub_path

@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        if 'file' not in request.files:
            return 'No file part'
        file = request.files['file']
        if file.filename == '':
            return 'No selected file'
        if file and file.filename.endswith('.epub'):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            images = extract_images_and_descriptions(file_path)
            return render_template('edit.html', images=images, filename=filename)
    return render_template('upload.html')

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
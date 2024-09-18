def update_epub_descriptions(epub_path, new_descriptions):
    temp_dir = tempfile.mkdtemp()
    new_epub_path = os.path.join(temp_dir, 'updated_' + os.path.basename(epub_path))
    
    with zipfile.ZipFile(epub_path, 'r') as zip_ref:
        with zipfile.ZipFile(new_epub_path, 'w') as new_zip:
            for item in zip_ref.infolist():
                with zip_ref.open(item.filename) as file:
                    if item.filename.endswith(('.xhtml', '.html', '.htm')):
                        content = file.read().decode('utf-8')
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
                                
                        new_zip.writestr(item.filename, str(soup))
                    else:
                        new_zip.writestr(item.filename, file.read())
    return new_epub_path
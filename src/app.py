import os
import sys
import subprocess
import re
import json
import tempfile
import io
import argparse

# 3rd party dependencies:
from flask import Flask, request, Response, render_template,jsonify

app = Flask(__name__)
app.config['TESTING'] = True
config = {
    'base_path': "./"
}

def init():
    global config
    return

def get_own_path():
    return os.path.dirname(__file__)

def sanitize_input(text:str):
    # remove special chars that are relevant for LaTex parsing
    text = text.replace('$','')
    text = text.replace('\\','')
    return text

def get_template_path():
    return get_own_path() + '/latex/template.tex'

def exec(cmd):
    print(' '.join(cmd))
    subprocess.run(cmd, shell=False, check=True)

def escape_tex(tex_code):
    """
    Escape special characters from the input so that they don't mess up our LaTeX file.
    """
    return re.sub(r'([_{}\\#])', r'\\\1', tex_code)
    

def generate_box(tibetan:str, above:str, below:str, has_border:bool, is_root_level:bool=True):
    """
    Generate a box with Tibetan text and possible annotations
    """
    contains_other_boxes = re.search(r'[[(]',tibetan + above + below )

    # recursive processing to allow for nested boxes
    tibetan = generate_boxes_for_chunk(tibetan, False)
    above = generate_boxes_for_chunk(above, False)
    below = generate_boxes_for_chunk(below, False)

    space = ' \linebreak[1] ' if is_root_level else ''

    # generate boxes for the current chunk
    if has_border:
        if not above and not below:
            return f'\\boxOnly{{{tibetan}}}{space}'
        if above and below or ( not contains_other_boxes ):
            # boxes with text above and below or innermost nesting level
            return  f'\\tibAboveBelow{{{tibetan}}}{{{above}}}{{{below}}}{space}'
        if above and not below:
            return f'\\tibAbove{{{tibetan}}}{{{above}}}{space}'
        if below and not above:
            return f'\\tibBelow{{{tibetan}}}{{{below}}}{space}'
    else:
        if not above and not below:
            # If there is only a brace without any annotation then we keep the brace around
            return f' ({tibetan}) '
        else:
            return f'\\tibAboveBelowNoBorder{{{tibetan}}}{{{above}}}{{{below}}}'

def generate_boxes_for_chunk(text:str, is_root_level:bool):
    if not text:
        return ''

    result = ''
    start_pos, end_pos, nesting, pos = 0, 0, 0, 0
    colons = []

    for idx, char in enumerate(text):
        if char == '(' or char == '[':
            nesting += 1 
            if nesting == 1:
                start_pos = idx
                colons = []

        elif char == ')' or char == ']':
            if nesting == 1:
                end_pos = idx
                result += text[pos:start_pos].strip()

                if len(colons) == 0:
                    colons.insert(0,start_pos)
                    colons.insert(0,start_pos)
                elif len(colons) == 1:
                    colons.insert(1,colons[0])

                below = text[start_pos + 1:colons[0]].strip()
                above = text[colons[0]+1:colons[1]].strip()
                tibetan = text[colons[1]+1:end_pos].strip()

                result += generate_box(tibetan, above, below, char == ']', is_root_level=is_root_level)

                pos = idx + 1

            if nesting > 0:
                nesting -= 1 
        
        elif char == ':' and nesting == 1:
            colons.append(idx)

    result += escape_tex(text[pos:].strip())
    return result

def handle_custom_commands(markdown_text:str):
    """
    Handle custom markdown commands, currently only ##anchorname to generate 
    a LaTeX nav target (anchor)
    """
    # replace ##anchorname with \hypertarget{anchorname}{}
    markdown_text = re.sub('##([A-Za-z]*)',r'\\hypertarget{\1}{\\label{\1}}',markdown_text)
    return markdown_text

def merge_multiline_tibetan(markdown_text:str):
    """
    If a block of Tibetan spans multiple lines, we merge them into a single one.
    This allows to add line breaks in the code more easily so that the lines in the source 
    text do not become too long
    """
    result = ''
    inside_tib_block = False

    for line in markdown_text.split('\n'):
        line = handle_custom_commands(line)
        if line.startswith('> ') or line.startswith('>> '):
            if inside_tib_block:
                # we are continuing on the next input line 
                # within a Tibetan block -> merge with the previous line
                result += ' ' + line[2:].strip()
            else:
                result += '\n' + line

            inside_tib_block = True
        else:
            inside_tib_block = False
            result += '\n' + line
    
    return result
        
def generate_boxes(markdown_text:str):
    lines = []

    markdown_text = merge_multiline_tibetan(markdown_text)
    for line in markdown_text.split('\n'):
        if line.startswith('> ') or line.startswith('>> '):
            # blockquote line -> do boxing
            prefix = '> ' if line.startswith('>> ') else ''
            line_content = generate_boxes_for_chunk(line[2:].strip(), is_root_level=True)
            lines.append( f'{prefix}\\tibetanfont{{{line_content}}}\\englishfont' )
        else:
            # normal line -> no boxing
            lines.append( line )
        
    return '\n'.join(lines)

def insert_navigation_anchor(markdown_text, cursor_line):
    """
    insert an invisible navigation anchor somewhat above the cursor position so that the scroll position 
    of the  PDF output is roughly the same as the position that is being edited.
    """
    
    # scroll the PDF output to some lines above the current cursor position
    view_position = max(0, cursor_line - 12)
    lines = markdown_text.split('\n')
    
    # if the desired position where we want to insert the anchor is in the middle of a Tibetan block 
    # then go up further
    while view_position > 0 and lines[view_position].startswith('>'):
        view_position -= 1

    # insert a navigation anchor
    lines.insert(view_position, '##viewPosition')

    return '\n'.join(lines)

def convert_markdown(markdown_text:str, format:str='latex', cursor_line:int=0):
    """
    Converts markdown to text

    Parameters:
    - markdown_text: The markdown code to be converted 
    - format: target format - 'latex' or 'pdf'
    """
    os.chdir('/tmp')

    markdown_text = insert_navigation_anchor(markdown_text, cursor_line)
    markdown_text = generate_boxes(markdown_text)

    md_file = tempfile.NamedTemporaryFile(prefix='boxing_', suffix='.md', delete=False) 
    base_name = md_file.name.replace('.md','')
    tex_file_name = base_name + '.tex'

    base_file_name = os.path.basename(base_name)

    with md_file:
        md_file.write(markdown_text.encode('utf-8'))

    exec([
        'pandoc',
        md_file.name, 
        f'--template={get_template_path()}',
        '-t', 'latex',
        '-s',
        '-o', tex_file_name,
    ])

    os.remove(md_file.name)

    if format == 'latex':
        with open(tex_file_name,'r', encoding="utf-8") as tex_file:
            tex = tex_file.read()    
        os.remove(tex_file_name)    
        return tex
    elif format == 'pdf':
        output_temp_path = '/tmp/'

        exec([
            'xelatex',
            '-synctex=1 ',
            '-no-shell-escape '
            f'-output-directory={output_temp_path} '
            '-interaction=nonstopmode',
            tex_file_name,
        ])

        output_base_name = output_temp_path + base_file_name

        pdf_file_name = output_base_name + '.pdf'
        print(pdf_file_name)
        with open(pdf_file_name, 'rb') as pdf_file:
            pdf = pdf_file.read()

        os.remove(tex_file_name)    
        os.remove(pdf_file_name)
        os.remove(output_base_name + '.aux')
        os.remove(output_base_name + '.log')
        os.remove(output_base_name + '.synctex.gz')
        
        return pdf

@app.route('/', methods=['GET'], strict_slashes=False)
def get_index():
    with open(f'{get_own_path()}/README.md', encoding="utf-8") as welcome_file:
        welcome = welcome_file.read()

    if "work_file" in config:
        del config['work_file']

    return render_template('index.html', welcome=welcome)

@app.route('/get_files')
def get_files():
    root_path = config['base_path'] # Change this to your folder path
    files = []
    for root, dirs, filenames in os.walk(root_path):
        level = root.replace(root_path, '').count(os.sep)
        rel_path  = root.replace(root_path, '')
        if rel_path.startswith("/") :
            rel_path = rel_path[1:]

        parent_folder = os.path.basename(os.path.dirname(root))
        files.append({'name': os.path.basename(root), 'type': 'folder', 'level': level, 'parent': parent_folder, 'path': rel_path})
        for filename in filenames:
            if filename.endswith('.md'):
                files.append({'name': filename, 'type': 'file', 'level': level + 1,  'parent': os.path.basename(root), 'path': os.path.join(rel_path, filename)})
    
    return jsonify(files)

@app.route('/read_file', methods=['POST'])
def read_file():
    file_name = request.form.get('file_name')
    file_path = os.path.join(config['base_path'], file_name)

    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            file_contents = file.read()

        config['work_file'] = file_path
        return jsonify({'success': True, 'file_contents': file_contents})
    else:
        return jsonify({'success': False, 'message': 'File not found'})


@app.route('/generate', methods=['POST'])
def generate():
    file_extension = ''
    markdown = request.form["textInput"]

    format = request.form["format"]
    cursor_line = int(request.form["cursorLine"]) if "cursorLine" in request.form else 0
    forceDownload = request.form["forceDownload"] == 'true'

    if format == 'latex':
        file_extension = 'tex'
        format = 'latex'
        mimetype = 'application/latex'
    elif format == 'pdf':
        file_extension = 'pdf'
        format = 'pdf'
        mimetype = 'application/pdf'
    else:
        file_extension = 'md'
        format = 'md'
        mimetype = 'text/markdown'

    markdown = sanitize_input(markdown)

    print("====" * 10)
    print(config)

    if 'work_file' in config:
        work_file = config['work_file']
        # Write the new content to the file
        with open(work_file, 'w') as f:
            f.write(markdown)
        print("Save file change to ", work_file)

    if format == 'md':
        output = markdown
    else:
        output = convert_markdown(markdown, format=format, cursor_line=cursor_line)

    if forceDownload:
        headers = {'Content-Disposition': f'attachment; filename="BoxedTibetan.{file_extension}'}
        mimetype = 'application/octet-stream'
    else:
        headers = {'Content-Disposition': f'inline; filename="BoxedTibetan.{file_extension}'}

    return Response(output, mimetype=mimetype, headers=headers)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Read the first command-line argument")
    parser.add_argument('--file_dir', type=str, default="", help="The first command-line argument")
    args = parser.parse_args()
    file_dir = args.file_dir

    if file_dir:
        config['base_path'] = os.path.abspath(file_dir)
    else:
        config['base_path'] = os.getcwd()

    print("Start app from path: ", config['base_path'], ".....")

    
    app.run()
    
    
application = app

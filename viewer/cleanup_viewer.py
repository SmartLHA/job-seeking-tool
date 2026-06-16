#!/usr/bin/env python3
with open('viewer_server.py', 'rb') as f:
    content = f.read()

content = content.replace(b"            print('[DEBUG] matched system-kanban path!', file=sys.stderr)\n", b'')
content = content.replace(b"                sys.stderr.write(\"[DEBUG] calling handle_api_system_kanban, store=\" + repr(_system_kanban_store) + chr(10)); sys.stderr.flush()\n", b'')
content = content.replace(b"            print(f'[DEBUG] system-kanban data len={len(data)}', file=sys.stderr)\n", b'')
content = content.replace(b"            print(f'[DEBUG] sending response to client...', file=sys.stderr)\n", b'')
content = content.replace(b"            print(f'[DEBUG] about to sendall resp len={len(resp)}', file=sys.stderr)\n", b'')
content = content.replace(b"            print(f'[DEBUG] sendall complete', file=sys.stderr)\n", b'')

old_error = b'    except Exception as e:\n        import traceback\n        sys.stderr.write(chr(10) + "[ERROR] handle_request exception: " + str(e) + chr(10))\n        sys.stderr.write(traceback.format_exc() + chr(10))\n        sys.stderr.flush()'
new_error = b'    except Exception:\n        pass'
content = content.replace(old_error, new_error)

with open('viewer_server.py', 'wb') as f:
    f.write(content)
print('Cleaned up')

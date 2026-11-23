"""No private hosting account is bundled with the public starter."""
def prepare(root):
    raise ValueError('No hosting account configured. Use the manual SFTP tab or implement your own reviewed publishing adapter.')
def prepare_test_page(root,file):
    return prepare(root)

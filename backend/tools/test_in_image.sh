#!/bin/sh
# Runs the backend tests inside a built nexpaper image, where ocrmypdf and Tesseract are installed: the tests of the
# text recognition run there instead of being skipped. The image is not changed: a throwaway container adds pytest and
# reads the repository (mounted read-only) as the tests expect it.
#
#   docker build -t nexpaper:test .
#   sh backend/tools/test_in_image.sh nexpaper:test                      # the tests of text and search
#   sh backend/tools/test_in_image.sh nexpaper:test tests                # everything
#
# Run from the root of the repository.
set -eu
image="${1:?the image to test}"
shift
targets="${*:-tests/test_ocr.py tests/test_similar_text.py tests/test_text.py tests/test_search.py tests/test_processing.py}"
exec docker run --rm --network bridge --entrypoint sh -v "$(pwd):/repo:ro" "$image" -c "
  set -e
  pip install --no-cache-dir -q --root-user-action=ignore -r /repo/backend/requirements-dev.txt
  cd /repo/backend && python -m pytest -q -p no:cacheprovider -rs $targets
"

FROM python:3.10

ENV TZ=UTC

RUN apt-get update && \
    apt-get install -y bind9 dnsutils tzdata

# TODO: avoid this
# RUN rm /etc/bind/rndc.key

RUN ln -fs /usr/share/zoneinfo/$TZ /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata

WORKDIR /code
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt
COPY . /code/
# COPY ./templates /code/templates
# COPY ./static /code/static
# COPY ./app /code/app

# Run directly
# CMD ["fastapi", "run", "app/main.py", "--port", "80"]

# Run after a reverse proxy
CMD ["fastapi", "run", "app/main.py", "--proxy-headers", "--port", "80"]

FROM php:8.2-fpm-alpine3.20

ARG WORDPRESS_DOWNLOAD_URL

USER root

WORKDIR /

ENV MUSL_LOCPATH /usr/share/i18n/locales/musl

RUN apk add --update --upgrade --no-cache --no-interactive --no-progress  \
    curl \
    freetype-dev \
    gcc \
    gettext-dev \
    gifsicle \
    git \
    gmp-dev \
    icu-dev \
    jpeg-dev \
    jpegoptim \
    libintl \
    libjpeg-turbo-dev \
    libpng-dev \
    libxml2-utils \
    libwebp-dev \
    make \
    musl-dev \
    musl-locales \
    musl-locales-lang \
    nginx \
    oniguruma-dev \
    openssl \
    optipng \
    pngquant \
    unzip \
 && docker-php-ext-configure gd  \
 && docker-php-ext-install gd gmp intl pdo pdo_mysql mbstring mysqli \
 && docker-php-ext-enable mysqli opcache

COPY ./build/local.ini /usr/local/etc/php/conf.d/local.ini
COPY ./build/nginx.conf /etc/nginx/nginx.conf

RUN rm -rf /var/www/html/
WORKDIR /var/www/html

RUN curl -sLfo wordpress.tar.gz ${WORDPRESS_DOWNLOAD_URL} \
 && tar -xvkf wordpress.tar.gz --strip-components=1 \
 && rm wordpress.tar.gz

RUN rm -rf license.txt readme.html wp-config-sample.php


COPY /code/config/wp-config.php /var/www/html/wp-config.php
COPY /code/plugins /var/www/html/wp-content/plugins/
COPY /code/themes /var/www/html/wp-content/themes/
COPY /code/languages /var/www/html/wp-content/languages/
COPY /code/uploads /var/www/html/wp-content/uploads/
COPY /build/robots.txt /var/www/html
COPY /code/.htaccess /var/www/html

COPY ./build/get_plugins.sh /get_plugins.sh
COPY ./build/plugins.txt /plugins.txt

RUN chmod +x /get_plugins.sh \
 && sh /get_plugins.sh \
 && rm -rf /get_plugins.sh

RUN chown -R www-data:www-data /var/www/html/ \
 && chown -R www-data:www-data /var/lib/nginx/

EXPOSE 8080
RUN nginx -t

COPY ./build/post_deploy.sh /post_deploy.sh

RUN ["chmod", "+x", "/post_deploy.sh"]

CMD [ "sh", "/post_deploy.sh" ]
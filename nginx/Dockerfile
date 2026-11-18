FROM nginx:alpine

# Replace the default nginx config with our reverse-proxy + static config.
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Static frontend assets.
COPY html/ /usr/share/nginx/html/

EXPOSE 80

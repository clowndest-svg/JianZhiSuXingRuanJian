docker exec xiaoye-release cp /etc/nginx/conf.d/default.conf /etc/nginx/conf.d/default.conf.bak

cat << 'EOF' | docker exec -i xiaoye-release tee /etc/nginx/conf.d/default.conf > /dev/null
server {
    listen       80;
    listen  [::]:80;
    server_name  localhost;

    # Preserved existing service manifests for xiaoye
    location = /latest.json {
        root   /usr/share/nginx/html;
    }

    location = /latest-extensions.json {
        root   /usr/share/nginx/html;
    }

    # Reverse proxy all QingSu Web & API & Uploads to FastAPI backend
    location / {
        proxy_pass http://172.17.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    error_page   500 502 503 504  /50x.html;
    location = /50x.html {
        root   /usr/share/nginx/html;
    }
}
EOF

docker exec xiaoye-release nginx -t
docker exec xiaoye-release nginx -s reload

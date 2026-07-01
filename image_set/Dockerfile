FROM ubuntu:22.04
RUN apt-get update && apt-get install -y nginx iputils-ping net-tools && \
    rm -rf /var/lib/apt/lists/*

# UAV/UGV 카메라 센서 모사용 테스트 이미지 복사
COPY attack_test_pool/ /var/www/html/images/

# 이미지 목록을 제공하는 JSON 인덱스 생성
RUN echo '{"images":["UAV_1.png","UAV_2.png","UAV_3.png","UAV_4.png","UGV_1.png","UGV_2.png","UGV_3.png","UGV_4.png","Missile_1.png","Missile_2.png","Missile_3.png","Missile_4.png"],"classes":{"UAV*":"UAV","UGV*":"UGV","Missile*":"Rocket"}}' \
    > /var/www/html/images/index.json

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]

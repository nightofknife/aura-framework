from airtest.core.api import *
import resource.function.city_guide as guide
import json
import multiprocessing


import resource.function.base_action as base


def entermap():
    for i in range(5):
        loc = exists(
            Template(filename="resource/template/guide/map_ui.png", resolution=(1280, 720)))
        if loc:
            touch(loc)
            return True
    return False


def searchcity(end_city_name=""):
    direction = 0
    flag = True
    while flag:
        loc = exists(Template(filename="resource/template/city/map/" + end_city_name + ".png", resolution=(1280, 720),
                              threshold=0.8))
        if loc:
            print("找到目标", end_city_name, "坐标", loc)
            touch(loc)
            return True
        match direction // 3:
            case 0:
                swipe((640, 140), (640, 620), duration=1)
                direction += 1
            case 1:
                swipe((1000, 360), (340, 360), duration=1)
                direction += 1
            case 2:
                swipe((640, 620), (640, 140), duration=1)
                direction += 1
            case 3:
                swipe((340, 360), (1000, 360), duration=1)
                direction += 1
        direction %= 12


def guidecity(start_city_name="", end_city_name=""):
    sleep(1)
    startcityloc = base.get_city_inf(city=start_city_name, information="maploc")
    endcityloc = base.get_city_inf(city=end_city_name, information="maploc")
    directionvector = [endcityloc[0] - startcityloc[0], endcityloc[1] - startcityloc[1]]
    k = 300 / max(directionvector, key=abs).__abs__()
    direction = (int(directionvector[0] * k), int(-directionvector[1] * k))
    print("目标方向为", direction)

    times = 8
    flag = True
    while flag and times > 0:
        # loc = exists(Template(filename="resource/template/city/map/" + end_city_name + ".png", resolution=(1280, 720),
        #                       threshold=0.8))
        loc = base.find_text_include_ocr(text=base.city_name_transition(end_city_name), rect=[120, 80, 1100, 600])
        if loc:
            print("找到目标", base.city_name_transition(end_city_name), "坐标", loc)
            touch([loc[0], loc[1] - 15])
            return True
        swipe((640 + direction[0] // 2, 360 - direction[1] // 2), (640 - direction[0] // 2, 360 + direction[1] // 2),
              duration=1)
        times -= 1
        sleep(0.5)
    return False


def travel(tree,goods):
    starttravel()
    # 计划，商品用0，白树用1，紫树用2 后续再加
    #目前商品是1，紫树是0，后续重新训练一个
    # todo 这里需要拆开tree的不同分类
    intravel(tree,goods)


def starttravel():
    touch(Template(filename="resource/template/guide/start_travel.png", resolution=(1280, 720)))


def intravel(tree=None,lost_goods=False):
    flag = True
    #临时测试用设置
    lost_goods = True
    if (tree or lost_goods) and False :
        while flag:
            for _ in range(20):
                result = base.recognition_by_model_yolo()
                for i in result:
                    if i[0] == 1 :
                        touch(i[1])
            loc = exists(Template(filename="resource/template/guide/end_travel.png", resolution=(1280, 720)))
            if loc:
                touch(loc)
                break
    else:
        while flag:
            loc = exists(Template(filename="resource/template/guide/end_travel.png", resolution=(1280, 720)))
            if loc:
                touch(loc)
                break
            sleep(5)

    for i in range(10):
        if guide.is_main():
            return True
        touch((620, 660))
        sleep(2)

    return False


# 这个是完整的测试逻辑
def city_travel(startcity="", endcity="",tree=None,goods=False):
    if endcity == "":
        print("无目标城市")
        return False
    entermap()
    print("开始寻找目标城市")
    if startcity != "":
        if not guidecity(start_city_name=startcity, end_city_name=endcity):
            searchcity(end_city_name=endcity)
    else:
        searchcity(end_city_name=endcity)
    print("找到了，开车")
    travel(tree,goods)
    print("开完了")
    return endcity

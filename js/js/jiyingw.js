var rule = {
	title:'极影网[磁]',
	host:'https://www.jiyingw.net',
	homeUrl:'/',
	url: '/fyclass/page/fypage?',
	filter_url:'{{fl.class}}',
	filter:{
		"movie":[{"key":"class","name":"标签","value":[{"n":"全部","v":"movie"},{"n":"4k","v":"tag/4k"}, {"n":"人性","v":"tag/人性"}, {"n":"传记","v":"tag/chuanji"}, {"n":"儿童","v":"tag/儿童"}, {"n":"冒险","v":"tag/adventure"}, {"n":"剧情","v":"tag/剧情"}, {"n":"加拿大","v":"tag/加拿大"}, {"n":"动作","v":"tag/dongzuo"}, {"n":"动漫","v":"tag/动漫"}, {"n":"励志","v":"tag/励志"}, {"n":"历史","v":"tag/history"}, {"n":"古装","v":"tag/古装"}, {"n":"同性","v":"tag/gay"}, {"n":"喜剧","v":"tag/comedy"}, {"n":"国剧","v":"tag/国剧"}, {"n":"奇幻","v":"tag/qihuan"}, {"n":"女性","v":"tag/女性"}, {"n":"家庭","v":"tag/family"}, {"n":"德国","v":"tag/德国"}, {"n":"恐怖","v":"tag/kongbu"}, {"n":"悬疑","v":"tag/xuanyi"}, {"n":"惊悚","v":"tag/jingsong"}, {"n":"意大利","v":"tag/意大利"}, {"n":"战争","v":"tag/zhanzheng"}, {"n":"战斗","v":"tag/战斗"}, {"n":"搞笑","v":"tag/搞笑"}, {"n":"故事","v":"tag/故事"}, {"n":"文艺","v":"tag/文艺"}, {"n":"日常","v":"tag/日常"}, {"n":"日本","v":"tag/日本"}, {"n":"日语","v":"tag/日语"}, {"n":"校园","v":"tag/校园"}, {"n":"武侠","v":"tag/wuxia"}, {"n":"法国","v":"tag/法国"}, {"n":"游戏","v":"tag/游戏"}, {"n":"灾难","v":"tag/zainan"}, {"n":"爱情","v":"tag/爱情"}, {"n":"犯罪","v":"tag/crime"}, {"n":"真人秀","v":"tag/zhenrenxiu"}, {"n":"短片","v":"tag/duanpian"}, {"n":"科幻","v":"tag/kehuan"}, {"n":"纪录","v":"tag/jilu"}, {"n":"美剧","v":"tag/meiju"}, {"n":"舞台","v":"tag/stage"}, {"n":"西部","v":"tag/xibu"}, {"n":"运动","v":"tag/yundong"}, {"n":"韩剧","v":"tag/韩剧"}, {"n":"韩国","v":"tag/韩国"}, {"n":"音乐","v":"tag/yinyue"}, {"n":"高清电影","v":"tag/高清电影"}]}]
	},
	searchUrl: '/?s=**',
	searchable:2,
	quickSearch:1,
	filterable:1,
	headers:{
		'User-Agent': 'PC_UA',
		'Referer': 'https://www.jiyingw.net/'
	},
	timeout:5000,
	class_name:'电影&电视剧&动漫&综艺&影评',
	class_url:'movie&tv&cartoon&movie/variety&yingping',
	play_parse:false,
	lazy:'',
	limit:6,
	推荐:'ul#post_container li;a&&title;img&&src;.article entry_post&&Text;a&&href',
        一级:'ul#post_container li;a&&title;img&&src;.article entry_post&&Text;a&&href',
	二级:{
		title:"h1&&Text",
		img:"#post_content img&&src",
		desc:"#post_content&&Text",
		content:".movie-introduce&&Text",
		tabs:`js:
			pdfh=jsp.pdfh;pdfa=jsp.pdfa;pd=jsp.pd;
			TABS=[]
			var d = pdfa(html, 'p.down-list3');
			var index=0;
			d.forEach(function(it) {
				let burl = pdfh(it, 'a&&href');
				log("burl >>>>>>" + burl);
				if (burl.startsWith("magnet")){
					let result = 'magnet' + index;
					index = index + 1;
					TABS.push(result);
				}
			});
			log('TABS >>>>>>>>>>>>>>>>>>' + TABS);
		`,
		lists:`js:
			log(TABS);
			pdfh=jsp.pdfh;pdfa=jsp.pdfa;pd=jsp.pd;
			LISTS = [];
			var d = pdfa(html, 'p.down-list3');
			TABS.forEach(function(tab) {
				log('tab >>>>>>>>' + tab);
				if (/^magnet/.test(tab)) {
					let targetindex = parseInt(tab.substring(6));
					let index = 0;
					d.forEach(function(it){
						let burl = pdfh(it, 'a&&href');
						if (burl.startsWith("magnet")){
							if (index == targetindex){
								let title = pdfh(it, 'a&&Text');
								log('title >>>>>>>>>>>>>>>>>>>>>>>>>>' + title);
								log('burl >>>>>>>>>>>>>>>>>>>>>>>>>>' + burl);
								let loopresult = title + '$' + burl;
								LISTS.push([loopresult]);
							}
							index = index + 1;
						}
					});
				}
			});
			`,

	},
	搜索:'#post_container li.post;a.zoom&&title;a.zoom img&&src;.info&&Text;a&&href;.article&&Text',
	预处理:`
		let new_host=HOST;
		let new_html=request(new_host, {withHeaders:true});
		let json=JSON.parse(new_html);
		let setCk=Object.keys(json).find(it=>it.toLowerCase()==="set-cookie");
		let cookie=setCk?json[setCk].split(";")[0]:"";
		log("cookie:"+cookie);
		rule_fetch_params.headers.Cookie=cookie;
		setItem(RULE_CK,cookie);
	`,
}

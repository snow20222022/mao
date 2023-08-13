var rule = {
	title:'MP4电影[磁]',
	host:'https://www.mp4us.com',
        homeUrl: '/',
	url: '/list/fyclass-fypage.html?',
	filter_url:'{{fl.class}}',
	filter:{
	},
	searchUrl: '/search/#nobot=1&wd=**;post',
	searchable:2,
	quickSearch:1,
	filterable:0,
	headers:{
		'User-Agent': 'PC_UA',
		'Referer': 'https://www.mp4us.com/',
	},
	timeout:5000,
	class_name: '动作片&科幻片&爱情片&喜剧片&恐怖片&战争片&剧情片&纪录片&动画片&电视剧',
	class_url: '1&2&3&4&5&6&7&8&9&10',
	play_parse:false,
	lazy:'',
	limit:6,
	推荐:'div.index_update ul li;a&&Text;;b&&Text;a&&href',
	一级:'div#list_all ul li;img.lazy&&alt;img.lazy&&data-original;span.update_time&&Text;a&&href',
	二级:{
		title:"div.article-header h1&&Text",
		img:"div.article-header div.pic img&&src",
		desc:'div.article-header div.text&&Text',
		content:'div.article-related.info p&&Text',
		tabs:`js:
			pdfh=jsp.pdfh;pdfa=jsp.pdfa;pd=jsp.pd;
			TABS=[]
			var d = pdfa(html, 'ul.down-list&&li');
			let magnetIndex=0;
			let ed2kIndex=0;
			d.forEach(function(it) {
				let burl = pdfh(it, 'a&&href');
				log("burl >>>>>>" + burl);
				if (burl.startsWith("magnet")){
					let result = 'magnet' + magnetIndex;
					magnetIndex = magnetIndex + 1;
					TABS.push(result);
				}
			});
			d.forEach(function(it) {
				let burl = pdfh(it, 'a&&href');
				log("burl >>>>>>" + burl);
				if (burl.startsWith("ed2k")){
					let result = 'ed2k' + ed2kIndex;
					ed2kIndex = ed2kIndex + 1;
					TABS.push(result);
				}
			});
			log('TABS >>>>>>>>>>>>>>>>>>' + TABS);
		`,
		lists:`js:
			log(TABS);
			pdfh=jsp.pdfh;pdfa=jsp.pdfa;pd=jsp.pd;
			LISTS = [];
			var d = pdfa(html, 'ul.down-list&&li');
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
			TABS.forEach(function(tab) {
				log('tab >>>>>>>>' + tab);
				if (/^ed2k/.test(tab)) {
					let targetindex = parseInt(tab.substring(4));
					let index = 0;
					d.forEach(function(it){
						let burl = pdfh(it, 'a&&href');
						if (burl.startsWith("ed2k")){
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
	搜索:'div#list_all li;img.lazy&&alt;img.lazy&&src;div.text_info h2&&Text;a&&href;p.info&&Text',
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

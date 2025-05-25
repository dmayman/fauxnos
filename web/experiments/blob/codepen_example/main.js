//ignore this file for now
var radius = 8;
TweenMax.staggerFromTo('.blob', 4 ,{
    cycle: {
        attr:function(i) {
            var r = i*90;
            var rand = Math.random();
            return {
                transform:'rotate('+r+') translate('+radius*5+',0.1) rotate('+(-r)+')'
            }      
        }
    },
    ease:Linear.easeNone,
    repeat:-1  
}
,{
    cycle: {
        attr:function(i) {
            var r = i*90+360;
            return {
                transform:'rotate('+r+') translate('+radius*5+',0.1) rotate('+(-r)+')'
            }      
        }
    },
    ease:Linear.easeNone,
    repeat:-1
}
);

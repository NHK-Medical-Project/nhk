$(function(){
	//People Love Slider
$('.hero-slide').slick({
  infinite: true,
  arrows: false,
  dots: true,
  autoplay: false,
  speed: 500,
  slidesToShow: 1,
  slidesToScroll: 1
});

//Client Slider
$('.trust-slider').slick({
  dots: true,
  infinite: true,
  arrows: false,
  autoplay: true,
  speed: 500,
  slidesToShow: 5,
  slidesToScroll: 1,
  responsive: [
    {
      breakpoint: 1024,
      settings: {
        slidesToShow: 3,
        slidesToScroll: 1,
        infinite: true,
        dots: false
      }
    },
    {
      breakpoint: 600,
      settings: {
        slidesToShow: 1,
        slidesToScroll: 1
      }
    },
    {
      breakpoint: 480,
      settings: {
        slidesToShow: 2.5,
		dots: false,
		autoplay: true,
        slidesToScroll: 1
      }
    }
  ]
});

//Client Slider
$('.price-slider').slick({
  dots: false,
  infinite: true,
  arrows: false,
  autoplay: false,
  centerMode: true,
  centerPadding: '0',
  speed: 500,
  slidesToShow: 3,
  slidesToScroll: 1,
  responsive: [
    {
      breakpoint: 1024,
      settings: {
        slidesToShow: 2,
        slidesToScroll: 1,
        infinite: true,
        dots: false
      }
    },
    {
      breakpoint: 600,
      settings: {
        slidesToShow: 1,
        slidesToScroll: 1
      }
    },
    {
      breakpoint: 480,
      settings: {
        slidesToShow: 1,
		centerMode: true,
		centerPadding: '20px',
        slidesToScroll: 1
      }
    }
  ]
});

//Client Slider
$('.client-slider').slick({
  dots: true,
  infinite: true,
  arrows: false,
  autoplay: true,
  centerMode: true,
  centerPadding: '0',
  speed: 500,
  slidesToShow: 3,
  slidesToScroll: 1,
  responsive: [
    {
      breakpoint: 1024,
      settings: {
        slidesToShow: 2,
        slidesToScroll: 1,
        infinite: true,
        dots: true
      }
    },
    {
      breakpoint: 600,
      settings: {
        slidesToShow: 1,
        slidesToScroll: 1
      }
    },
    {
      breakpoint: 480,
      settings: {
        slidesToShow: 1,
		centerMode: false,
		centerPadding: '0',
        slidesToScroll: 1
      }
    }
  ]
});

//Blog Slider
$('.blog-slider').slick({
  dots: false,
  infinite: true,
  arrows: false,
  autoplay: true,
  slide: '.slick-slideshow__slide',
  centerMode: true,
  centerPadding: '250px',
  speed: 500,
  slidesToShow: 3,
  slidesToScroll: 1,
  responsive: [
    {
      breakpoint: 1024,
      settings: {
        slidesToShow: 2,
        slidesToScroll: 1,
        infinite: true,
        dots: true
      }
    },
    {
      breakpoint: 600,
      settings: {
        slidesToShow: 1,
        slidesToScroll: 1
      }
    },
    {
      breakpoint: 480,
      settings: {
        slidesToShow: 1,
		centerPadding: '100px',  
        slidesToScroll: 1
      }
    }
  ]
});

//Project page slider

$('.slider-for').slick({
    slidesToShow: 1,
    slidesToScroll: 1,
    arrows: false,
    fade: true,
    asNavFor: '.slider-nav'
});
$('.slider-nav').slick({
    slidesToShow: 4,
    slidesToScroll: 1,
    vertical:true,
    asNavFor: '.slider-for',
    dots: false,
    focusOnSelect: true,
    verticalSwiping:true,
    responsive: [
    {
        breakpoint: 992,
        settings: {
          vertical: false,
        }
    },
    {
      breakpoint: 768,
      settings: {
        vertical: false,
      }
    },
    {
      breakpoint: 580,
      settings: {
        vertical: false,
        slidesToShow: 3,
      }
    },
    {
      breakpoint: 380,
      settings: {
        vertical: false,
        slidesToShow: 3,
      }
    }
    ]
});

//Blog page 
$('.slider-blog').slick({
  infinite: true,
  arrows: false,
  dots: true,
  autoplay: false,
  speed: 500,
  slidesToShow: 1,
  slidesToScroll: 1
});


//$(document).ready(function(){
//	
//  
//  
//});
	
	$(".fa-search").click(function(){
    $(".wrap, .input").toggleClass("active");
    $("input[type='text']").focus();
  });
    
 

 var $carousel = $('.slider');
function setSlideVisibility() {
  //Find the visible slides i.e. where aria-hidden="false"
  var visibleSlides = $carousel.find('.slick-slideshow__slide[aria-hidden="false"]');
  //Make sure all of the visible slides have an opacity of 1
  $(visibleSlides).each(function() {
    $(this).css('opacity', 1);
  });

  //Set the opacity of the first and last partial slides.
  $(visibleSlides).first().prev().css('opacity', 0);
}


//$carousel.slick(settings); 
$carousel.slick('slickGoTo', 1);
setSlideVisibility();

$carousel.on('afterChange', function() {
  setSlideVisibility();
});

//Counter 
$('.count').each(function () {
    $(this).prop('Counter',0).animate({
        Counter: $(this).text()
    }, {
        duration: 3000,
        easing: 'swing',
        step: function (now) {
            $(this).text(Math.ceil(now));
        }
    });
});	





//Number Type
const typedTextSpan = document.querySelector(".typed-text");
const cursorSpan = document.querySelector(".cursor");

const textArray = ["Sales", "Custom Mobile App", "ERP Solutions"];
const typingDelay = 100;
const erasingDelay = 70;
const newTextDelay = 1000; // Delay between current and next text
let textArrayIndex = 0;
let charIndex = 0;

function type() {
  if (charIndex < textArray[textArrayIndex].length) {
    if(!cursorSpan.classList.contains("typing")) cursorSpan.classList.add("typing");
    typedTextSpan.textContent += textArray[textArrayIndex].charAt(charIndex);
    charIndex++;
    setTimeout(type, typingDelay);
  } 
  else {
    cursorSpan.classList.remove("typing");
  	setTimeout(erase, newTextDelay);
  }
}
function erase() {
	if (charIndex > 0) {
    if(!cursorSpan.classList.contains("typing")) cursorSpan.classList.add("typing");
    typedTextSpan.textContent = textArray[textArrayIndex].substring(0, charIndex-1);
    charIndex--;
    setTimeout(erase, erasingDelay);
  } 
  else {
    cursorSpan.classList.remove("typing");
    textArrayIndex++;
    if(textArrayIndex>=textArray.length) textArrayIndex=0;
    setTimeout(type, typingDelay + 1100);
  }
}

document.addEventListener("DOMContentLoaded", function() { // On DOM Load initiate the effect
  if(textArray.length) setTimeout(type, newTextDelay + 250);
});


})


 
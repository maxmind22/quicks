
button = document.getElementById('submit');
button.addEventListener("click", send);

messageDiv = document.getElementsByClassName("results");




function send(e){
  e.preventDefault();  
  text = (document.getElementsByClassName('form-control'))[0].value;
  let newDiv = document.createElement("div");
  newDiv.classList.add("query", "rst", "meChat","alert", "alert-primary");
  newDiv.textContent = text;
  let newDiv2 = document.createElement("div");
  newDiv2.classList.add("server","alert", "alert-secondary");
  messageDiv[0].appendChild(newDiv);
  document.getElementsByClassName('form-control')[0].value = "";


  // send query to server
  $.ajax({
    url: "/search",
    type: "post",
    datatype: "application/json",
    data: {query:JSON.stringify(text)},

    success: (response) => {
      newDiv2.textContent = response;
      messageDiv[0].appendChild(newDiv2);
  }
  })

};


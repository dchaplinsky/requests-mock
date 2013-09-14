requests-mock
=============

My messy attempt to record and replay requests made by [python-requests](https://github.com/kennethreitz/requests) library.

Idea is simple: each request is recorded and stored in key-value storage with
request fingerprint as a key. 
Fingerprint of request is SHA1 checksum of HTTP method, url, params, body and
traceback for this request. You can configure which fields of traceback you want
to include to the fingerprint with `tb_ignores` param.

You can also filter out those requests that shouldn't be cached with `filters` param by passing a list
of callables to the `patch_requests` method.

At the moment all recorded requests are stored in memory. However you can 
create your own caching backend by subclassing `CacheStorage` class and implementing
`get` and `put` methods

Why
=============
Well. It's proof of concept now but the main idea is that testing of the code
that relies on 3-rd party APIs (like [BrainTree](https://github.com/braintree/braintree_python) 
or [GoCardless](https://github.com/gocardless/gocardless-python)) is pita. APIs are
slow, you might have some limits on amount of requests/operations, et cetera.
With requests-mock on the other hand you can record your test execution and then
replay it with all requests retrieved from cache. At least that's an idea.

Credits
=============
A lot of code for fingerprints has been ripped^W borrowed from [Scrapy](https://github.com/scrapy/scrapy), the awesome
scraping framework.

Code to make response objects pickleable is borrowed from Taneli Kaivola's [pull request](https://github.com/tanelikaivola/requests/commit/a5360defdc3f91f4178e2aa1d7136a39a06b2a54)
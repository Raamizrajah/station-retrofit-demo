using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using StationRetrofit.Api.Data;
using StationRetrofit.Api.Dtos;
using StationRetrofit.Api.Models;

namespace StationRetrofit.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
[Produces("application/json")]
public class ProductsController : ControllerBase
{
    private readonly AppDbContext _db;

    public ProductsController(AppDbContext db)
    {
        _db = db;
    }

    /// <summary>List all products with price count.</summary>
    [HttpGet(Name = "ListProducts")]
    [EndpointName("ListProducts")]
    [ProducesResponseType(typeof(List<ProductDto>), StatusCodes.Status200OK)]
    public async Task<IActionResult> ListProducts()
    {
        var products = await _db.Products
            .Include(p => p.PriceEntries)
            .OrderByDescending(p => p.CreatedAt)
            .Select(p => new ProductDto(
                p.Id,
                p.Name,
                p.Sku,
                p.Status,
                p.CreatedAt,
                p.PriceEntries.Count))
            .ToListAsync();

        return Ok(products);
    }

    /// <summary>Get a single product with its prices.</summary>
    [HttpGet("{id:int}", Name = "GetProduct")]
    [EndpointName("GetProduct")]
    [ProducesResponseType(typeof(ProductDto), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> GetProduct(int id)
    {
        var product = await _db.Products
            .Include(p => p.PriceEntries)
            .FirstOrDefaultAsync(p => p.Id == id);

        if (product is null)
            return NotFound();

        var dto = new ProductDto(
            product.Id,
            product.Name,
            product.Sku,
            product.Status,
            product.CreatedAt,
            product.PriceEntries.Count);

        return Ok(dto);
    }

    /// <summary>Create a new product.</summary>
    [HttpPost(Name = "CreateProduct")]
    [EndpointName("CreateProduct")]
    [ProducesResponseType(typeof(ProductDto), StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> CreateProduct([FromBody] CreateProductRequest request)
    {
        var product = new Product
        {
            Name = request.Name,
            Sku = request.Sku,
            Status = ProductStatus.Draft,
            CreatedAt = DateTime.UtcNow,
            UpdatedAt = DateTime.UtcNow
        };

        _db.Products.Add(product);
        await _db.SaveChangesAsync();

        var dto = new ProductDto(product.Id, product.Name, product.Sku, product.Status, product.CreatedAt, 0);
        return CreatedAtRoute("GetProduct", new { id = product.Id }, dto);
    }

    /// <summary>Update an existing product.</summary>
    [HttpPut("{id:int}", Name = "UpdateProduct")]
    [EndpointName("UpdateProduct")]
    [ProducesResponseType(typeof(ProductDto), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> UpdateProduct(int id, [FromBody] UpdateProductRequest request)
    {
        var product = await _db.Products
            .Include(p => p.PriceEntries)
            .FirstOrDefaultAsync(p => p.Id == id);

        if (product is null)
            return NotFound();

        if (request.Name is not null)
            product.Name = request.Name;

        if (request.Sku is not null)
            product.Sku = request.Sku;

        if (request.Status.HasValue)
            product.Status = request.Status.Value;

        product.UpdatedAt = DateTime.UtcNow;
        await _db.SaveChangesAsync();

        var dto = new ProductDto(product.Id, product.Name, product.Sku, product.Status, product.CreatedAt, product.PriceEntries.Count);
        return Ok(dto);
    }

    /// <summary>Delete a product and its prices.</summary>
    [HttpDelete("{id:int}", Name = "DeleteProduct")]
    [EndpointName("DeleteProduct")]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> DeleteProduct(int id)
    {
        var product = await _db.Products.FindAsync(id);

        if (product is null)
            return NotFound();

        _db.Products.Remove(product);
        await _db.SaveChangesAsync();

        return NoContent();
    }
}

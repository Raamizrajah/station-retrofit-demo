using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using StationRetrofit.Api.Data;
using StationRetrofit.Api.Dtos;
using StationRetrofit.Api.Models;

namespace StationRetrofit.Api.Controllers;

[ApiController]
[Route("api/[controller]")]
[Produces("application/json")]
public class PricesController : ControllerBase
{
    private readonly AppDbContext _db;

    public PricesController(AppDbContext db)
    {
        _db = db;
    }

    /// <summary>List price entries, optionally filtered by product.</summary>
    [HttpGet(Name = "ListPrices")]
    [EndpointName("ListPrices")]
    [ProducesResponseType(typeof(List<PriceEntryDto>), StatusCodes.Status200OK)]
    public async Task<IActionResult> ListPrices([FromQuery] int? productId)
    {
        var query = _db.PriceEntries.AsQueryable();

        if (productId.HasValue)
            query = query.Where(p => p.ProductId == productId.Value);

        var prices = await query
            .OrderByDescending(p => p.ValidFrom)
            .Select(p => new PriceEntryDto(
                p.Id,
                p.ProductId,
                p.Currency,
                p.Amount,
                p.Type,
                p.ValidFrom,
                p.ValidTo))
            .ToListAsync();

        return Ok(prices);
    }

    /// <summary>Create a new price entry.</summary>
    [HttpPost(Name = "CreatePrice")]
    [EndpointName("CreatePrice")]
    [ProducesResponseType(typeof(PriceEntryDto), StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<IActionResult> CreatePrice([FromBody] CreatePriceRequest request)
    {
        var productExists = await _db.Products.AnyAsync(p => p.Id == request.ProductId);
        if (!productExists)
            return BadRequest(new { error = $"Product {request.ProductId} not found." });

        var entry = new PriceEntry
        {
            ProductId = request.ProductId,
            Currency = request.Currency,
            Amount = request.Amount,
            Type = request.Type,
            ValidFrom = request.ValidFrom,
            ValidTo = request.ValidTo,
            CreatedAt = DateTime.UtcNow
        };

        _db.PriceEntries.Add(entry);
        await _db.SaveChangesAsync();

        var dto = new PriceEntryDto(entry.Id, entry.ProductId, entry.Currency, entry.Amount, entry.Type, entry.ValidFrom, entry.ValidTo);
        return Created($"/api/prices/{entry.Id}", dto);
    }

    /// <summary>Delete a price entry.</summary>
    [HttpDelete("{id:int}", Name = "DeletePrice")]
    [EndpointName("DeletePrice")]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> DeletePrice(int id)
    {
        var entry = await _db.PriceEntries.FindAsync(id);

        if (entry is null)
            return NotFound();

        _db.PriceEntries.Remove(entry);
        await _db.SaveChangesAsync();

        return NoContent();
    }
}
